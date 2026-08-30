import Foundation

/// Start / Stop / Restart, each confirmed against the process itself.
///
/// A control that reports what it ASKED FOR is worse than no control: firing
/// the command and flipping the label to "running" would show a green dot for a
/// process that died on startup. Every action here therefore ends by polling
/// the PID file and signalling the process until the state actually changed, or
/// reporting honestly that it did not.
@MainActor
final class Control: ObservableObject {
    enum Action: String { case start = "Start", stop = "Stop", restart = "Restart" }

    enum Status: Equatable {
        case idle
        case working(String)
        case failed(String)
    }

    @Published private(set) var status: Status = .idle

    private let home: URL
    private var pidFile: URL { home.appendingPathComponent("runtime/torin_main.pid") }

    /// Startup does dependency preflight and service init before it writes a
    /// PID, so the window has to be generous; shutdown drains workers.
    private let startTimeout: TimeInterval = 90
    private let stopTimeout: TimeInterval = 45

    init(home: URL) { self.home = home }

    var isBusy: Bool { if case .working = status { return true }; return false }

    func clearFailure() { if case .failed = status { status = .idle } }

    func livePID() -> Int32? {
        guard let text = try? String(contentsOf: pidFile, encoding: .utf8),
              let pid = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines))
        else { return nil }
        // EPERM means it exists and belongs to someone else -- still alive.
        return (kill(pid, 0) == 0 || errno == EPERM) ? pid : nil
    }

    func perform(_ action: Action) {
        guard !isBusy else { return }
        status = .working(action == .stop ? "Stopping…"
                          : action == .start ? "Starting…" : "Restarting…")

        Task.detached { [weak self] in
            guard let self else { return }
            do {
                switch action {
                case .stop:
                    try await self.stopAndConfirm()
                case .start:
                    try await self.startAndConfirm()
                case .restart:
                    // Order matters and both halves are verified: a restart that
                    // silently skipped the stop would leave the old process up
                    // and the new one refusing with "already running".
                    if await self.livePID() != nil { try await self.stopAndConfirm() }
                    try await self.startAndConfirm()
                }
                await MainActor.run { self.status = .idle }
            } catch {
                let why = (error as? Failure)?.reason ?? error.localizedDescription
                await MainActor.run { self.status = .failed(why) }
            }
        }
    }

    struct Failure: Error { let reason: String }

    private func startAndConfirm() async throws {
        if await livePID() != nil {
            throw Failure(reason: "TorinAI is already running")
        }
        let log = home.appendingPathComponent("logs/torin_launch.log").path
        // Detached: TorinAI must outlive this window. Without nohup + disown the
        // substrate would die whenever the dashboard was closed.
        let command = """
        cd '\(home.path)' && nohup ./torin > '\(log)' 2>&1 &
        disown
        """
        try run("/bin/bash", ["-lc", command], env: ["TORIN_LAUNCHER": "app"])

        if let pid = try await waitFor(startTimeout, until: { await self.livePID() != nil }) as Int32?? {
            _ = pid
            return
        }
        throw Failure(reason: "did not start within \(Int(startTimeout))s — see logs/torin_launch.log")
    }

    private func stopAndConfirm() async throws {
        guard await livePID() != nil else { return }          // already down
        try run(home.appendingPathComponent("torin-stop").path, [], env: [:])

        if (try await waitFor(stopTimeout, until: { await self.livePID() == nil })) != nil {
            return
        }
        throw Failure(reason: "still running after \(Int(stopTimeout))s — use torin-kill")
    }

    /// Poll until the condition holds, or give up. Returns nil on timeout.
    private func waitFor(_ timeout: TimeInterval,
                         until condition: @escaping () async -> Bool) async throws -> Int32? {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await condition() { return 0 }
            try await Task.sleep(nanoseconds: 500_000_000)
        }
        return nil
    }

    private nonisolated func run(_ launchPath: String, _ args: [String],
                                 env: [String: String]) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: launchPath)
        process.arguments = args
        process.currentDirectoryURL = URL(fileURLWithPath:
            "/Users/stefan/Dominion Labs/TorinAI")
        var environment = ProcessInfo.processInfo.environment
        env.forEach { environment[$0.key] = $0.value }
        process.environment = environment
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        try process.run()
        process.waitUntilExit()
    }
}
