import Foundation
import LocalAuthentication
import SwiftUI

/// Approval requests, and the two buttons that answer them.
///
/// The bell is the only place the substrate can ask a person for something, so
/// it must never be able to show "nothing waiting" for the wrong reason: a
/// failed read is rendered as an error inside the popover, not as an empty
/// list, because an empty bell reads as "you are not needed".
///
/// The queries live in `core.governance.approval_requests` and are reached
/// through `torin-approvals`, for the same reason `Feed` shells out to
/// `torin-feed` — a Swift copy of the decision rules would be a second opinion
/// about what an approval means.
struct Approval: Identifiable, Equatable {
    let id: Int
    let actionId: String
    let tier: String
    let scope: String
    let requester: String
    let summary: String
    let rationale: String
    let created: String
    let status: String
    let decidedBy: String
    let components: [String]
    let improvements: [String]

    var isPending: Bool { status == "pending" }

    /// MAJOR and TRANSFORMATIVE are the two scopes the deployment gate stops.
    var isSevere: Bool { tier == "TRANSFORMATIVE" }
}

@MainActor
final class Approvals: ObservableObject {
    @Published private(set) var pending: [Approval] = []
    @Published private(set) var recent: [Approval] = []
    @Published private(set) var lastError: String?
    @Published private(set) var deciding: Set<Int> = []

    private let home: URL
    private let python: URL
    private var timer: Timer?

    init(home: URL) {
        self.home = home
        self.python = home.appendingPathComponent("venv_torin/bin/python3")
    }

    func start() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { _ in
            Task { @MainActor in self.refresh() }
        }
    }

    func stop() { timer?.invalidate(); timer = nil }

    /// NEVER ON THE MAIN THREAD.
    ///
    /// This ran the subprocess synchronously inside a @MainActor method, so
    /// every poll blocked the UI for as long as the helper took — and the
    /// helper imported the whole `core` package, which measured at 19.5
    /// seconds. Polling that every 5 seconds meant the window was blocked
    /// essentially always: it never finished loading and had to be force
    /// quit. The helper is now ~0.12s, but the fix is BOTH — a fast call on
    /// the main thread is still a call that can hang on a stalled database.
    func refresh() {
        Task.detached(priority: .utility) { [weak self] in
            guard let self else { return }
            let data = await self.runOffMain(["--json"])
            await MainActor.run { self.apply(data) }
        }
    }

    private func apply(_ data: Data?) {
        guard let data else { return }               // runOffMain already reported
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            lastError = "approvals returned unreadable output"
            return
        }
        if let failure = root["error"] as? String {
            // KEEP WHAT WAS ALREADY SHOWN. Blanking the list on a transient
            // read failure would make a waiting request vanish from the bell.
            lastError = failure
            return
        }
        lastError = nil
        pending = decode(root["pending"])
        recent = decode(root["recent"])
    }

    private func decode(_ raw: Any?) -> [Approval] {
        guard let rows = raw as? [[String: Any]] else { return [] }
        return rows.compactMap { row in
            guard let id = row["approval_id"] as? Int else { return nil }
            let details = row["details"] as? [String: Any] ?? [:]
            return Approval(
                id: id,
                actionId: row["action_id"] as? String ?? "",
                tier: row["tier"] as? String ?? "",
                scope: row["scope"] as? String ?? "",
                requester: row["requester"] as? String ?? "",
                summary: row["summary"] as? String ?? "",
                rationale: row["rationale"] as? String ?? "",
                created: String((row["created_at"] as? String ?? "").prefix(19))
                    .replacingOccurrences(of: "T", with: " "),
                status: row["status"] as? String ?? "",
                decidedBy: row["decided_by"] as? String ?? "",
                components: details["components"] as? [String] ?? [],
                improvements: details["improvements"] as? [String] ?? [])
        }
    }

    /// Approving a self-modification re-authenticates. Unlocking the window
    /// earlier proves someone opened it; this proves someone is still there
    /// when the substrate is told it may change itself.
    func decide(_ approval: Approval, approve: Bool) {
        guard !deciding.contains(approval.id) else { return }
        deciding.insert(approval.id)

        let finish: (Bool, String) -> Void = { [weak self] authenticated, who in
            guard let self else { return }
            let flag = approve ? "--approve" : "--decline"
            var args = [flag, String(approval.id), "--by", who]
            if authenticated { args.append("--authenticated") }

            Task.detached(priority: .userInitiated) { [weak self] in
                guard let self else { return }
                let data = await self.runOffMain(args)
                await MainActor.run {
                    if let data,
                       let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let failure = root["error"] as? String {
                        self.lastError = failure
                    }
                    self.deciding.remove(approval.id)
                    self.refresh()
                }
            }
        }

        // A DECLINE NEEDS NO BIOMETRY. Refusing is the safe direction, and
        // making it harder than approving would be exactly backwards.
        guard approve else {
            finish(false, NSFullUserName())
            return
        }

        let context = LAContext()
        context.localizedCancelTitle = "Cancel"
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            // Record the approval WITHOUT the authenticated flag rather than
            // claiming an authentication that did not happen.
            finish(false, NSFullUserName())
            return
        }
        context.evaluatePolicy(.deviceOwnerAuthentication,
                               localizedReason: "approve a TorinAI self-modification") {
            ok, _ in
            Task { @MainActor in
                if ok {
                    finish(true, NSFullUserName())
                } else {
                    self.deciding.remove(approval.id)   // cancelled: nothing recorded
                }
            }
        }
    }

    /// Runs the helper off the main actor and gives up rather than hanging.
    ///
    /// `nonisolated` so it cannot be called on the UI thread by accident, and
    /// it reports failures by hopping back to the main actor rather than
    /// touching @Published state from a background thread.
    private nonisolated func runOffMain(_ args: [String]) async -> Data? {
        let pythonPath = await python.path
        let root = await home
        guard FileManager.default.isExecutableFile(atPath: pythonPath) else {
            await MainActor.run { self.lastError = "venv_torin python not found at \(pythonPath)" }
            return nil
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = [root.appendingPathComponent("torin-approvals").path] + args
        process.currentDirectoryURL = root
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()

        do {
            try process.run()
        } catch {
            let why = error.localizedDescription
            await MainActor.run { self.lastError = why }
            return nil
        }

        // A HELPER THAT NEVER RETURNS MUST NOT BECOME A DASHBOARD THAT NEVER
        // RETURNS. Reading to EOF is unbounded; if the database is unreachable
        // and the client hangs, this kills it and says so instead of stalling
        // every later poll behind it.
        let deadline = Date().addingTimeInterval(20)
        while process.isRunning && Date() < deadline {
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
        if process.isRunning {
            process.terminate()
            await MainActor.run {
                self.lastError = "torin-approvals did not answer within 20s"
            }
            return nil
        }

        return pipe.fileHandleForReading.readDataToEndOfFile()
    }
}

// MARK: - The bell

struct NotificationBell: View {
    @ObservedObject var approvals: Approvals
    @State private var open = false

    private var count: Int { approvals.pending.count }

    var body: some View {
        Button { open.toggle() } label: {
            ZStack(alignment: .topTrailing) {
                Image(systemName: count > 0 ? "bell.badge.fill" : "bell")
                    .font(.system(size: 13))
                    .foregroundStyle(count > 0
                                     ? Color(red: 1.0, green: 0.54, blue: 0.10)
                                     : Color.secondary)
                if count > 0 {
                    Text("\(count)")
                        .font(.system(size: 9, weight: .bold, design: .rounded))
                        .foregroundStyle(.black)
                        .padding(.horizontal, 4).padding(.vertical, 1)
                        .background(Capsule().fill(Color(red: 1.0, green: 0.54, blue: 0.10)))
                        .offset(x: 9, y: -7)
                }
            }
            .frame(width: 26, height: 18)
        }
        .buttonStyle(.plain)
        .help(count > 0 ? "\(count) waiting for you" : "Notifications")
        .popover(isPresented: $open, arrowEdge: .bottom) {
            NotificationCenterView(approvals: approvals)
        }
    }
}

struct NotificationCenterView: View {
    @ObservedObject var approvals: Approvals

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Notifications")
                    .font(.system(size: 12, weight: .bold, design: .rounded))
                Spacer()
                Text(approvals.pending.isEmpty ? "nothing waiting"
                     : "\(approvals.pending.count) waiting")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 12).padding(.vertical, 9)

            Divider()

            if let failure = approvals.lastError {
                // NOT an empty list. A read that failed must not look like a
                // system with nothing to ask.
                HStack(alignment: .top, spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                    Text(failure).textSelection(.enabled)
                }
                .font(.system(size: 11)).foregroundStyle(.red)
                .padding(12)
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 8) {
                    if approvals.pending.isEmpty && approvals.lastError == nil {
                        Text("No approvals are waiting.")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                            .padding(.vertical, 14).padding(.horizontal, 12)
                    }

                    ForEach(approvals.pending) { approval in
                        ApprovalCard(approval: approval, approvals: approvals)
                    }

                    if !approvals.recent.isEmpty {
                        Text("RECENTLY DECIDED")
                            .font(.system(size: 9, weight: .bold, design: .monospaced))
                            .foregroundStyle(.tertiary)
                            .padding(.top, 6).padding(.horizontal, 12)
                        ForEach(approvals.recent.prefix(6)) { approval in
                            DecidedRow(approval: approval)
                        }
                    }
                }
                .padding(.vertical, 10)
            }
        }
        .frame(width: 420, height: 460)
    }
}

struct ApprovalCard: View {
    let approval: Approval
    @ObservedObject var approvals: Approvals

    private var busy: Bool { approvals.deciding.contains(approval.id) }
    private var accent: Color {
        approval.isSevere ? .red : Color(red: 1.0, green: 0.54, blue: 0.10)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 6) {
                Text(approval.tier)
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundStyle(.black)
                    .padding(.horizontal, 5).padding(.vertical, 1.5)
                    .background(RoundedRectangle(cornerRadius: 3).fill(accent))
                Text(approval.requester)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(approval.created)
                    .font(.system(size: 9.5, design: .monospaced))
                    .foregroundStyle(.tertiary)
            }

            Text(approval.summary)
                .font(.system(size: 12, weight: .medium))
                .fixedSize(horizontal: false, vertical: true)

            if !approval.rationale.isEmpty {
                Text(approval.rationale)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if !approval.components.isEmpty {
                Text(approval.components.joined(separator: " · "))
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 8) {
                if busy {
                    ProgressView().controlSize(.mini).scaleEffect(0.7)
                    Text("recording…").font(.system(size: 10)).foregroundStyle(.secondary)
                } else {
                    Button {
                        approvals.decide(approval, approve: true)
                    } label: {
                        Label("Approve", systemImage: "checkmark.circle.fill")
                            .font(.system(size: 11, weight: .medium))
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                    .tint(Color(red: 0.16, green: 0.62, blue: 0.38))

                    Button {
                        approvals.decide(approval, approve: false)
                    } label: {
                        Label("Decline", systemImage: "xmark.circle.fill")
                            .font(.system(size: 11, weight: .medium))
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)

                    Spacer()
                    Image(systemName: "touchid")
                        .font(.system(size: 10))
                        .foregroundStyle(.tertiary)
                        .help("Approving requires Touch ID")
                }
            }
            .padding(.top, 1)
        }
        .padding(10)
        .background(Color.white.opacity(0.04))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(accent.opacity(0.35), lineWidth: 1))
        .padding(.horizontal, 10)
    }
}

struct DecidedRow: View {
    let approval: Approval

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: approval.status == "approved"
                  ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.system(size: 10))
                .foregroundStyle(approval.status == "approved" ? .green : .red)
            Text(approval.summary)
                .font(.system(size: 10.5))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Spacer()
            Text(approval.decidedBy)
                .font(.system(size: 9.5, design: .monospaced))
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 12)
    }
}
