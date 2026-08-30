import Foundation

/// Where the panes get their records.
///
/// Deliberately the SAME sources torin-dash reads, and the same rules: channel
/// files when TorinAI is running, the combined log routed after the fact when it
/// is not, and Torin's own recorded events for the substrate. Re-deriving the
/// routing table here would give the app a second opinion about which channel a
/// module belongs to, so the table is parsed from channels.py rather than copied.
enum Channel: String, CaseIterable, Identifiable {
    case substrate, system, security, health
    var id: String { rawValue }

    var title: String { rawValue.uppercased() }

    var subtitle: String {
        switch self {
        case .substrate: return "thinking · acting · learning · memory"
        case .system:    return "database · tools · api · services"
        case .security:  return "evaluations · contracts · audit"
        case .health:    return "monitoring · watchdog · recovery"
        }
    }
}

struct Entry: Identifiable, Equatable {
    /// STABLE ACROSS POLLS. This was `UUID()`, regenerated on every refresh, so
    /// each 2-second poll produced an entirely new set of identities: SwiftUI
    /// rebuilt every row, the scroll position jumped, and `onChange(count)`
    /// could not tell an appended record from a redrawn one. Deriving the id
    /// from the content means an unchanged record keeps its identity and only
    /// genuinely new records animate in -- which is what makes it stream.
    var id: String { "\(time)|\(source)|\(message)" }
    let time: String
    let level: String
    let source: String
    let message: String
    var isRecordedEvent = false
}

@MainActor
final class Feed: ObservableObject {
    @Published var entries: [Channel: [Entry]] = [:]
    @Published var origin: [Channel: String] = [:]
    @Published var running = false
    @Published var lastError: String?

    private let home: URL
    private let python: URL
    private var timer: Timer?

    init(home: URL) {
        self.home = home
        self.python = home.appendingPathComponent("venv_torin/bin/python3")
    }

    func start() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { _ in
            Task { @MainActor in self.refresh() }
        }
    }

    func stop() { timer?.invalidate(); timer = nil }

    private func refresh() {
        running = isRunning()
        // ONE reader, in Python, rather than a Swift reimplementation of the
        // channel routing and the raw_event query. Both were verified against
        // live data; duplicating them here would mean two things to keep right.
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            lastError = "venv_torin python not found at \(python.path)"
            return
        }
        let process = Process()
        process.executableURL = python
        process.arguments = [home.appendingPathComponent("torin-feed").path, "--json"]
        process.currentDirectoryURL = home
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            decode(data)
        } catch {
            lastError = error.localizedDescription
        }
    }

    private func decode(_ data: Data) {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            lastError = "feed returned unreadable output"
            return
        }
        lastError = root["error"] as? String
        var next: [Channel: [Entry]] = [:]
        var origins: [Channel: String] = [:]
        for channel in Channel.allCases {
            guard let block = root[channel.rawValue] as? [String: Any] else { continue }
            origins[channel] = block["origin"] as? String ?? ""
            let rows = block["entries"] as? [[String: Any]] ?? []
            next[channel] = rows.map {
                Entry(time: $0["time"] as? String ?? "",
                      level: $0["level"] as? String ?? "",
                      source: $0["source"] as? String ?? "",
                      message: $0["message"] as? String ?? "",
                      isRecordedEvent: $0["event"] as? Bool ?? false)
            }
        }
        // APPEND, don't replace. Swapping the whole array each poll made the
        // list flicker and re-scroll even when nothing had changed; merging on
        // identity keeps existing rows in place and adds only what arrived.
        for (channel, incoming) in next {
            let existing = entries[channel] ?? []
            if existing.isEmpty {
                entries[channel] = incoming
                continue
            }
            let known = Set(existing.map(\.id))
            let fresh = incoming.filter { !known.contains($0.id) }
            if !fresh.isEmpty {
                entries[channel] = Array((existing + fresh).suffix(400))
            }
        }
        for channel in Channel.allCases where next[channel] == nil {
            entries[channel] = []
        }
        origin = origins
    }

    private func isRunning() -> Bool {
        let pidFile = home.appendingPathComponent("runtime/torin_main.pid")
        guard let text = try? String(contentsOf: pidFile, encoding: .utf8),
              let pid = Int32(text.trimmingCharacters(in: .whitespacesAndNewlines))
        else { return false }
        return kill(pid, 0) == 0 || errno == EPERM
    }
}
