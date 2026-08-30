import SwiftUI

let torinHome = URL(fileURLWithPath: "/Users/stefan/Dominion Labs/TorinAI")

@main
struct TorinDashboardApp: App {
    @StateObject private var gate = Gate()
    @StateObject private var feed = Feed(home: torinHome)
    @StateObject private var control = Control(home: torinHome)
    @StateObject private var approvals = Approvals(home: torinHome)
    @StateObject private var systems = Systems(home: torinHome)
    @StateObject private var components = Components(home: torinHome)

    var body: some Scene {
        WindowGroup("TorinAI") {
            Group {
                if gate.state == .unlocked {
                    DashboardView(feed: feed, gate: gate, control: control,
                                  approvals: approvals, systems: systems, components: components)
                        .onAppear { feed.start(); approvals.start(); systems.start(); components.start() }
                        .onDisappear { feed.stop(); approvals.stop(); systems.stop(); components.stop() }
                } else {
                    LockView(gate: gate)
                }
            }
            .frame(minWidth: 900, minHeight: 560)
            .background(Color(red: 0.07, green: 0.08, blue: 0.10))
            .preferredColorScheme(.dark)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1180, height: 760)
    }
}

struct LockView: View {
    @ObservedObject var gate: Gate

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "touchid")
                .font(.system(size: 54, weight: .light))
                .foregroundStyle(Color(red: 1.0, green: 0.54, blue: 0.10))
            Text("TorinAI").font(.system(size: 26, weight: .semibold, design: .rounded))
            Text("Touch ID required").font(.callout).foregroundStyle(.secondary)

            if case .failed(let why) = gate.state {
                // The OS already explained it; passing that through beats
                // replacing it with a generic refusal.
                Text(why)
                    .font(.footnote).foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 340)
            }

            if gate.state == .authenticating {
                ProgressView().controlSize(.small)
            } else {
                Button("Unlock") { gate.authenticate() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onAppear { if gate.state == .locked { gate.authenticate() } }
    }
}

enum DashTab: String, CaseIterable, Identifiable {
    case logs = "Logs"
    case monitoring = "Monitoring"
    case security = "Security"
    var id: String { rawValue }
}

struct DashboardView: View {
    @ObservedObject var feed: Feed
    @ObservedObject var gate: Gate
    @ObservedObject var control: Control
    @ObservedObject var approvals: Approvals
    @ObservedObject var systems: Systems
    @ObservedObject var components: Components
    @State private var tab: DashTab = .logs

    private func pane(_ channel: Channel, _ height: CGFloat) -> some View {
        PaneView(channel: channel,
                 entries: feed.entries[channel] ?? [],
                 origin: feed.origin[channel] ?? "")
            .frame(maxWidth: .infinity)
            .frame(height: max(120, height))
    }

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Text("TorinAI").font(.system(size: 15, weight: .bold, design: .rounded))
                    .foregroundStyle(Color(red: 1.0, green: 0.54, blue: 0.10))
                Text("dashboard").foregroundStyle(.secondary).font(.system(size: 13))
                Spacer()

                // Enabled by ACTUAL state: Start is offered only when nothing is
                // running, Stop only when something is. A control that can be
                // pressed in a state where it cannot work invites the report of
                // a change that never happened.
                ControlButton(title: "Start", icon: "play.fill",
                              enabled: !feed.running && !control.isBusy) {
                    control.perform(.start)
                }
                ControlButton(title: "Stop", icon: "stop.fill",
                              enabled: feed.running && !control.isBusy) {
                    control.perform(.stop)
                }
                ControlButton(title: "Restart", icon: "arrow.clockwise",
                              enabled: feed.running && !control.isBusy) {
                    control.perform(.restart)
                }

                Divider().frame(height: 14).padding(.horizontal, 4)

                if case .working(let what) = control.status {
                    ProgressView().controlSize(.mini).scaleEffect(0.7)
                    Text(what).font(.system(size: 12)).foregroundStyle(.secondary)
                } else {
                    Circle().fill(feed.running ? .green : .gray).frame(width: 7, height: 7)
                    Text(feed.running ? "running" : "stopped")
                        .font(.system(size: 12)).foregroundStyle(.secondary)
                }

                NotificationBell(approvals: approvals)

                Button { gate.lock() } label: { Image(systemName: "lock.fill") }
                    .buttonStyle(.plain).help("Lock")
            }
            .padding(.horizontal, 14).padding(.top, 12)

            if case .failed(let why) = control.status {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                    Text(why).textSelection(.enabled)
                    Spacer()
                    Button("Dismiss") { control.clearFailure() }.buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                }
                .font(.system(size: 11)).foregroundStyle(.red)
                .padding(.horizontal, 14)
            } else if let error = feed.lastError {
                Text(error).font(.system(size: 11)).foregroundStyle(.red)
                    .padding(.horizontal, 14)
            }

            // THE WINDOW DIVIDES THE PANES, NOT THE CONTENT.
            //
            // This was a LazyVGrid, which sizes rows to their content -- so a
            // single long record stretched its pane and pushed the other three
            // off screen. Two fixed rows of two, each taking half the available
            // height, means a pane's height never depends on what is in it.
            // TAB STRIP. Logs is the streaming panes; Monitoring and Security
            // are the live-systems views with real status dots and controls.
            Picker("", selection: $tab) {
                ForEach(DashTab.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .frame(width: 320)
            .padding(.horizontal, 14)

            switch tab {
            case .logs:
                GeometryReader { geo in
                    let paneH = (geo.size.height - 12) / 2
                    VStack(spacing: 12) {
                        HStack(spacing: 12) {
                            pane(.substrate, paneH)
                            pane(.system, paneH)
                        }
                        HStack(spacing: 12) {
                            pane(.security, paneH)
                            pane(.health, paneH)
                        }
                    }
                }
                .padding(.horizontal, 12).padding(.bottom, 12)
            case .monitoring:
                ScrollView { ComponentsView(components: components) }
                    .padding(.horizontal, 12).padding(.bottom, 12)
            case .security:
                ScrollView { SystemsView(systems: systems, kind: "security") }
                    .padding(.horizontal, 12).padding(.bottom, 12)
            }
        }
    }
}

struct PaneView: View {
    let channel: Channel
    let entries: [Entry]
    let origin: String

    private var accent: Color {
        switch channel {
        case .substrate: return Color(red: 0.85, green: 0.45, blue: 0.95)
        case .health:    return Color(red: 0.35, green: 0.82, blue: 0.55)
        case .security:  return Color(red: 0.95, green: 0.78, blue: 0.30)
        case .system:    return Color(red: 0.55, green: 0.58, blue: 0.62)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text(channel.title).font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundStyle(accent)
                Spacer()
                Text("\(entries.count)\(origin == "torin_main.log" ? " · from torin_main.log" : "")")
                    .font(.system(size: 10, design: .monospaced)).foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 10).padding(.vertical, 7)

            Divider().overlay(accent.opacity(0.35))

            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 2) {
                        if entries.isEmpty {
                            Text("no records for this channel")
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundStyle(.tertiary).padding(8)
                        }
                        ForEach(entries) { entry in
                            EntryRow(entry: entry, accent: accent).id(entry.id)
                        }
                    }
                    .padding(.horizontal, 9).padding(.vertical, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: entries.count) {
                    if let last = entries.last { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
            HStack {
                Text(channel.subtitle).font(.system(size: 9.5)).foregroundStyle(.tertiary)
                Spacer()
            }
            .padding(.horizontal, 10).padding(.bottom, 6)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Color.white.opacity(0.03))
        .clipShape(RoundedRectangle(cornerRadius: 9))
        .overlay(RoundedRectangle(cornerRadius: 9).stroke(accent.opacity(0.30), lineWidth: 1))
    }
}

struct EntryRow: View {
    let entry: Entry
    let accent: Color

    private var levelColour: Color {
        switch entry.level {
        case "ERROR", "CRITICAL": return .red
        case "WARNING":           return .yellow
        default:                  return .primary.opacity(0.85)
        }
    }

    var body: some View {
        // ONE Text, not an HStack of four.
        //
        // Separate Texts each contribute their own intrinsic width, so a long
        // message widened the row, the row widened the pane, and the pane
        // widened the column -- the stretching was here, not in the layout.
        // Concatenated runs wrap as a single paragraph and cannot push outward.
        (Text(entry.time + "  ").foregroundStyle(.tertiary)
         + levelRun
         + Text(entry.source + "  ")
            .foregroundStyle(entry.isRecordedEvent ? accent : Color.secondary)
         + Text(entry.message).foregroundStyle(levelColour))
            .font(.system(size: 11, design: .monospaced))
            .lineLimit(4)
            .truncationMode(.tail)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .textSelection(.enabled)
    }

    private var levelRun: Text {
        guard !entry.level.isEmpty, entry.level != "INFO" else { return Text("") }
        return Text(String(entry.level.prefix(4)) + "  ").foregroundStyle(levelColour)
    }
}


struct ControlButton: View {
    let title: String
    let icon: String
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(.system(size: 11, weight: .medium))
                .labelStyle(.titleAndIcon)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .disabled(!enabled)
    }
}
