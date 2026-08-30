import Foundation
import SwiftUI

// One system as the dashboard sees it. Every field comes from the substrate's
// own status table via `torin-systems --status`; nothing here is invented.
struct SystemRow: Identifiable, Equatable {
    let name: String
    let kind: String            // "monitoring" or "security"
    let description: String
    let status: String          // running | stopped | absent | gate
    let controllable: Bool
    let ageSeconds: Int         // how old the published status is
    var id: String { name }
}

// Reads real status and issues real control, both across the process boundary
// through the same Python helper the rest of the app uses. This process cannot
// touch the live systems; the substrate does, on its own loop.
@MainActor
final class Systems: ObservableObject {
    @Published var rows: [SystemRow] = []
    @Published var lastError: String?
    @Published var busy: Set<String> = []      // systems with a command in flight

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

    func rows(for kind: String) -> [SystemRow] {
        rows.filter { $0.kind == kind }.sorted { $0.name < $1.name }
    }

    private var refreshing = false

    // OFF THE MAIN THREAD. The status read spawns a Python process and waits on
    // it, and that process opens a database connection -- hundreds of
    // milliseconds. Doing that on the main actor froze the UI every 2s. The
    // blocking work runs detached; only the published result touches main.
    //
    // `refreshing` drops a tick if the previous one has not returned, so a slow
    // read cannot pile up a backlog of subprocesses.
    private func refresh() {
        if refreshing { return }
        refreshing = true
        Task.detached { [python, home] in
            let data = Systems.shell(python: python, home: home, args: ["--status"])
            await MainActor.run { [weak self] in
                guard let self else { return }
                self.refreshing = false
                guard let data else { return }
                guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    self.lastError = "status feed returned unreadable output"; return
                }
                if let err = root["error"] as? String { self.lastError = err; return }
                self.lastError = nil
                let list = root["systems"] as? [[String: Any]] ?? []
                self.rows = list.map {
                    SystemRow(name: $0["name"] as? String ?? "?",
                              kind: $0["kind"] as? String ?? "?",
                              description: $0["description"] as? String ?? "",
                              status: $0["status"] as? String ?? "unknown",
                              controllable: $0["controllable"] as? Bool ?? false,
                              ageSeconds: ($0["age_seconds"] as? Int) ?? 0)
                }
            }
        }
    }

    // Enqueue a real command. The substrate applies it and the next refresh
    // shows the moved status, so the dot follows the actual system rather than
    // an optimistic guess made here.
    func control(_ system: String, _ action: String) {
        busy.insert(system)
        Task.detached { [python, home, weak self] in
            let out = Systems.shell(python: python, home: home,
                                    args: ["--control", system, action])
            guard let strongSelf = self else { return }
            await MainActor.run {
                strongSelf.busy.remove(system)
                if let data = out,
                   let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let reason = root["reason"] as? String, (root["ok"] as? Bool) == false {
                    strongSelf.lastError = "\(system): \(reason)"
                }
                strongSelf.refresh()
            }
        }
    }

    nonisolated static func shell(python: URL, home: URL, args: [String]) -> Data? {
        guard FileManager.default.isExecutableFile(atPath: python.path) else { return nil }
        let process = Process()
        process.executableURL = python
        process.arguments = [home.appendingPathComponent("torin-systems").path] + args
        process.currentDirectoryURL = home
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return data
        } catch { return nil }
    }
}

// The Monitoring / Security view. A colored dot per system, its description, and
// real Stop/Restart controls — or, for an always-on gate, an honest "always on"
// with no button rather than a control that could not do anything.
struct SystemsView: View {
    @ObservedObject var systems: Systems
    let kind: String            // "monitoring" or "security"

    private func dotColor(_ status: String) -> Color {
        switch status {
        case "running": return .green
        case "stopped": return .yellow
        case "gate":    return Color(red: 0.35, green: 0.70, blue: 0.95)
        case "absent":  return .gray
        default:        return .orange
        }
    }

    private func statusLabel(_ r: SystemRow) -> String {
        switch r.status {
        case "gate":   return "always on"
        case "absent": return "not running"
        default:       return r.status
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(systems.rows(for: kind)) { r in
                HStack(spacing: 10) {
                    Circle().fill(dotColor(r.status)).frame(width: 9, height: 9)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(r.name).font(.system(size: 13, weight: .medium, design: .monospaced))
                        Text(r.description).font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text(statusLabel(r)).font(.system(size: 11)).foregroundStyle(.secondary)
                        .frame(width: 78, alignment: .trailing)

                    if r.controllable {
                        if systems.busy.contains(r.name) {
                            ProgressView().controlSize(.mini).scaleEffect(0.7).frame(width: 132)
                        } else {
                            HStack(spacing: 6) {
                                Button("Stop") { systems.control(r.name, "stop") }
                                    .disabled(r.status != "running")
                                Button("Restart") { systems.control(r.name, "restart") }
                                    .disabled(r.status == "absent")
                                Button("Start") { systems.control(r.name, "start") }
                                    .disabled(r.status == "running" || r.status == "absent")
                            }
                            .buttonStyle(.bordered).controlSize(.small)
                            .frame(width: 132)
                        }
                    } else {
                        Text("").frame(width: 132)
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 8)
                Divider().opacity(0.25)
            }
            if systems.rows(for: kind).isEmpty {
                Text(systems.lastError ?? "no systems reported")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .padding(14)
            }
        }
    }
}

// One subsystem's health, for the Monitoring page. MONITORED, not controlled:
// a memory or reasoning subsystem is not something you stop, only something
// whose health you watch. No buttons -- an indicator light and a score.
struct Component: Identifiable, Equatable {
    let name: String
    let category: String
    let status: String
    let healthScore: Double
    let monitoringEnabled: Bool
    let checkedAge: Int?
    let owner: String            // "system" (always-on guardian) or "substrate"
    var id: String { name }
}

@MainActor
final class Components: ObservableObject {
    @Published var items: [Component] = []
    @Published var lastError: String?
    @Published var substratePresent: Bool = false

    private let home: URL
    private let python: URL
    private var timer: Timer?
    private var refreshing = false

    init(home: URL) {
        self.home = home
        self.python = home.appendingPathComponent("venv_torin/bin/python3")
    }

    func start() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { _ in
            Task { @MainActor in self.refresh() }
        }
    }
    func stop() { timer?.invalidate(); timer = nil }

    // Grouped by category, categories in order, for a sectioned list.
    var categories: [String] {
        Array(Set(items.map(\.category))).sorted()
    }
    func items(in category: String) -> [Component] {
        items.filter { $0.category == category }.sorted { $0.name < $1.name }
    }

    // Split by owner for the two sections of the Monitoring page. Always-on
    // system subsystems on top; the substrate's cognition below.
    var systemItems: [Component] {
        items.filter { $0.owner == "system" }.sorted { $0.name < $1.name }
    }
    var substrateItems: [Component] {
        items.filter { $0.owner == "substrate" }.sorted { $0.name < $1.name }
    }
    // A substrate subsystem is graded WITH the substrate; when it is stopped it
    // reads offline from the heartbeat, not from a stale score.
    func isOffline(_ c: Component) -> Bool {
        c.owner == "substrate" && !substratePresent
    }

    private func refresh() {
        if refreshing { return }
        refreshing = true
        Task.detached { [python, home] in
            let data = Systems.shell(python: python, home: home, args: ["--components"])
            await MainActor.run { [weak self] in
                guard let self else { return }
                self.refreshing = false
                guard let data,
                      let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else { return }
                if let err = root["error"] as? String { self.lastError = err; return }
                self.lastError = nil
                self.substratePresent = (root["substrate_present"] as? Bool) ?? false
                let list = root["components"] as? [[String: Any]] ?? []
                self.items = list.map {
                    Component(name: $0["name"] as? String ?? "?",
                              category: $0["category"] as? String ?? "other",
                              status: $0["status"] as? String ?? "unknown",
                              healthScore: ($0["health_score"] as? Double) ?? 0,
                              monitoringEnabled: ($0["monitoring_enabled"] as? Bool) ?? false,
                              checkedAge: $0["checked_age"] as? Int,
                              owner: $0["owner"] as? String ?? "system")
                }
            }
        }
    }
}

// The Monitoring page: every monitored subsystem with a health light. Read-only.
// Status → indicator color. Shared by the cards and the summary tally.
func componentLight(_ status: String) -> Color {
    switch status {
    case "healthy":                   return .green
    case "degraded":                  return .yellow
    case "unhealthy":                 return .orange
    case "critical":                  return .red
    case "offline":                   return Color(white: 0.45)   // host stopped
    case "declared", "not_monitored": return Color(white: 0.45)   // no live check yet
    default:                          return .gray
    }
}

// The Monitoring page: two owner sections (always-on System on top, Substrate
// cognition below), each a grid of cards. Read-only — a health light and a
// labeled health bar per subsystem, no controls.
struct ComponentsView: View {
    @ObservedObject var components: Components

    private let columns = [GridItem(.adaptive(minimum: 176), spacing: 12)]

    // Effective status: a substrate subsystem reads offline when the substrate
    // is down, regardless of the score left over from its last run.
    private func effStatus(_ c: Component) -> String {
        components.isOffline(c) ? "offline" : c.status
    }

    private func tally(_ items: [Component]) -> String {
        var healthy = 0, attention = 0, off = 0
        for c in items {
            switch effStatus(c) {
            case "healthy": healthy += 1
            case "offline": off += 1
            default: attention += 1
            }
        }
        var parts = ["\(healthy) healthy"]
        if attention > 0 { parts.append("\(attention) need attention") }
        if off > 0 { parts.append("\(off) offline") }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder
    private func section(_ title: String, _ subtitle: String, _ items: [Component]) -> some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(title)
                        .font(.system(size: 12, weight: .semibold))
                        .tracking(0.6)
                    Text(subtitle)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(tally(items))
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
                    ForEach(items) { c in
                        ComponentCard(name: c.name,
                                      status: effStatus(c),
                                      score: c.healthScore,
                                      offline: components.isOffline(c))
                    }
                }
            }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            if components.items.isEmpty {
                Text(components.lastError ?? "no subsystems reported")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
                    .padding(.top, 40)
            } else {
                section("SYSTEM", "always-on", components.systemItems)
                section("SUBSTRATE", "cognition", components.substrateItems)
            }
        }
        .padding(16)
    }
}

// One subsystem, as a card: name, a status light, and — when it is live — a
// labeled health bar so the number is never a bare, unexplained percentage.
struct ComponentCard: View {
    let name: String
    let status: String
    let score: Double        // 0…1
    let offline: Bool

    private var color: Color { componentLight(status) }
    private var pct: Int { max(0, min(100, Int((score * 100).rounded()))) }

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 7) {
                Circle().fill(color).frame(width: 7, height: 7)
                Text(name)
                    .font(.system(size: 12.5, weight: .medium, design: .monospaced))
                    .lineLimit(1).truncationMode(.tail)
                Spacer(minLength: 2)
            }
            Text(status.capitalized)
                .font(.system(size: 10.5, weight: .medium))
                .foregroundStyle(color)

            if offline {
                // No health bar for something intentionally stopped.
                Text("substrate stopped")
                    .font(.system(size: 9)).foregroundStyle(.secondary)
            } else {
                HStack(spacing: 6) {
                    Text("HEALTH")
                        .font(.system(size: 8, weight: .semibold)).tracking(0.5)
                        .foregroundStyle(.secondary)
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule().fill(Color.primary.opacity(0.08))
                            Capsule().fill(color)
                                .frame(width: max(3, geo.size.width * CGFloat(score)))
                        }
                    }
                    .frame(height: 4)
                    Text("\(pct)%")
                        .font(.system(size: 9.5, weight: .medium))
                        .foregroundStyle(.secondary)
                        .frame(width: 30, alignment: .trailing)
                }
            }
        }
        .padding(11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 9).fill(Color.primary.opacity(0.045)))
        .overlay(RoundedRectangle(cornerRadius: 9).stroke(Color.primary.opacity(0.09), lineWidth: 1))
        .opacity(offline ? 0.6 : 1)
    }
}
