import AppKit
import LLMUsageCore
import SwiftUI

/// The panel shown when the menu-bar item is clicked.
struct UsagePanel: View {
    let store: UsageStore
    let onSizeChange: (CGSize) -> Void
    @State private var openAtLogin = LaunchAtLogin.isEnabled

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            VStack(alignment: .leading, spacing: 10) {
                header(now: context.date)
                ForEach(store.visibleProviders) { provider in
                    ProviderCard(provider: provider, status: store.status(provider), now: context.date)
                }
                footer
            }
        }
        .padding(14)
        .frame(width: 310)
        .fixedSize(horizontal: false, vertical: true)
        .onGeometryChange(for: CGSize.self) { $0.size } action: { onSizeChange($0) }
        .onAppear { openAtLogin = LaunchAtLogin.isEnabled }
    }

    private func header(now: Date) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text("LLM Usage").font(.headline)
            Spacer()
            Group {
                if store.isRefreshing {
                    Text("Refreshing…")
                } else if let last = store.lastRefresh {
                    Text(now.timeIntervalSince(last) < 60 ? "Updated just now"
                         : "Updated \(last.formatted(.relative(presentation: .named, unitsStyle: .abbreviated)))")
                }
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            Button {
                Task { await store.refresh() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .symbolEffect(.rotate, isActive: store.isRefreshing)
            }
            .buttonStyle(.borderless)
            .disabled(store.isRefreshing)
            .help("Refresh")
        }
    }

    private var footer: some View {
        HStack {
            Toggle("Open at Login", isOn: $openAtLogin)
                .toggleStyle(.checkbox)
                .onChange(of: openAtLogin) { _, enabled in
                    LaunchAtLogin.set(enabled)
                    openAtLogin = LaunchAtLogin.isEnabled
                }
            Spacer()
            Button("Quit") { NSApp.terminate(nil) }
                .buttonStyle(.borderless)
                .keyboardShortcut("q")
        }
        .font(.caption)
        .padding(.top, 2)
    }
}

private struct ProviderCard: View {
    let provider: ProviderID
    let status: ProviderStatus
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 6) {
                ProviderIconView(provider: provider)
                    .frame(width: 14, height: 14)
                    .foregroundStyle(provider.accent)
                Text(provider.displayName).font(.subheadline.weight(.semibold))
                Spacer()
                if let credits = status.snapshot?.credits {
                    Text(credits.unlimited ? "Credits: unlimited"
                         : credits.balance.map { "Credits: \($0.formatted(.currency(code: "USD")))" } ?? "Credits")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            let snapshot = status.snapshot
            UsageRow(label: UsageFormat.windowLabel(snapshot?.session, fallback: "5h"),
                     window: snapshot?.session, accent: provider.accent, now: now)
            UsageRow(label: UsageFormat.windowLabel(snapshot?.weekly, fallback: "7d"),
                     window: snapshot?.weekly, accent: provider.accent, now: now)
            if let monthly = snapshot?.monthly {
                UsageRow(label: "mo", window: monthly, accent: provider.accent, now: now)
            }
            if let error = status.error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .padding(10)
        .background(.fill.quaternary, in: .rect(cornerRadius: 10))
        .opacity(status.snapshot == nil && status.error == nil ? 0.6 : 1)
    }
}

private struct UsageRow: View {
    let label: String
    let window: UsageWindow?
    let accent: Color
    let now: Date

    var body: some View {
        HStack(spacing: 8) {
            Text(label)
                .foregroundStyle(.secondary)
                .frame(width: 22, alignment: .leading)
            UsageBar(fraction: (window?.percent ?? 0) / 100, color: barColor)
                .frame(height: 6)
            Text(UsageFormat.percent(window?.percent))
                .frame(width: 34, alignment: .trailing)
            Text(UsageFormat.countdown(to: window?.resetsAt, now: now) ?? "–")
                .foregroundStyle(.secondary)
                .frame(width: 50, alignment: .trailing)
        }
        .font(.caption.monospacedDigit())
    }

    private var barColor: Color {
        guard let percent = window?.percent else { return accent }
        return percent >= 90 ? .red : accent
    }
}

private struct UsageBar: View {
    let fraction: Double
    let color: Color

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(.quaternary)
                Capsule()
                    .fill(color.gradient)
                    .frame(width: max(0, min(1, fraction)) * geo.size.width)
            }
        }
        .animation(.smooth, value: fraction)
    }
}
