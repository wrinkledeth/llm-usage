import AppKit
import LLMUsageCore
import SwiftUI

/// The panel shown when the menu-bar item is clicked.
struct UsagePanel: View {
    let store: UsageStore
    let onSizeChange: (CGSize) -> Void

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(store.visibleProviders.enumerated()), id: \.element) { index, provider in
                    if index > 0 {
                        Divider().opacity(0.4).padding(.vertical, 12)
                    }
                    ProviderSection(provider: provider, status: store.status(provider), now: context.date)
                }
                footer(now: context.date)
                    .padding(.top, 14)
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 16)
        .padding(.bottom, 10)
        .frame(width: 300)
        .fixedSize(horizontal: false, vertical: true)
        // The panel's hidden title bar would otherwise push everything down.
        .ignoresSafeArea()
        .onGeometryChange(for: CGSize.self) { $0.size } action: { onSizeChange($0) }
    }

    private func footer(now: Date) -> some View {
        HStack(spacing: 6) {
            Group {
                if store.isRefreshing {
                    Text("Refreshing…")
                } else if let last = store.lastRefresh {
                    Text(now.timeIntervalSince(last) < 60 ? "Updated just now"
                         : "Updated \(last.formatted(.relative(presentation: .named, unitsStyle: .abbreviated)))")
                }
            }
            .font(.caption2)
            .foregroundStyle(.tertiary)
            Spacer()
            Button {
                Task { await store.refresh() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .font(.caption.weight(.medium))
                    .symbolEffect(.rotate, isActive: store.isRefreshing)
            }
            .buttonStyle(.borderless)
            .foregroundStyle(.secondary)
            .disabled(store.isRefreshing)
            .help("Refresh")
        }
    }
}

private struct ProviderSection: View {
    let provider: ProviderID
    let status: ProviderStatus
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 7) {
                ProviderIconView(provider: provider)
                    .frame(width: 15, height: 15)
                    .foregroundStyle(provider.accent)
                Text(provider.displayName)
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                if let detail {
                    Text(detail)
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
                    .foregroundStyle(.orange)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
        }
        .opacity(status.snapshot == nil && status.error == nil ? 0.5 : 1)
    }

    private var detail: String? {
        guard let credits = status.snapshot?.credits else { return nil }
        if credits.unlimited { return "Unlimited credits" }
        return credits.balance.map { "\($0.formatted(.currency(code: "USD").precision(.fractionLength(0...2)))) credits" }
    }
}

private struct UsageRow: View {
    let label: String
    let window: UsageWindow?
    let accent: Color
    let now: Date

    var body: some View {
        HStack(spacing: 10) {
            Text(label)
                .font(.system(size: 11, weight: .medium).monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 20, alignment: .leading)
            UsageBar(fraction: (window?.percent ?? 0) / 100, color: barColor)
                .frame(height: 7)
            Text(UsageFormat.percent(window?.percent))
                .font(.system(size: 12, weight: .semibold).monospacedDigit())
                .frame(width: 36, alignment: .trailing)
            Text(UsageFormat.countdown(to: window?.resetsAt, now: now) ?? "")
                .font(.system(size: 11).monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 52, alignment: .trailing)
        }
    }

    private var barColor: Color {
        guard let percent = window?.percent else { return accent }
        if percent >= 90 { return .red }
        if percent >= 75 { return .orange }
        return accent
    }
}

private struct UsageBar: View {
    let fraction: Double
    let color: Color

    var body: some View {
        GeometryReader { geo in
            let clamped = max(0, min(1, fraction))
            ZStack(alignment: .leading) {
                Capsule().fill(.primary.opacity(0.16))
                if clamped > 0 {
                    Capsule()
                        .fill(color.gradient)
                        .frame(width: max(geo.size.height, clamped * geo.size.width))
                }
            }
        }
        .animation(.smooth, value: fraction)
    }
}
