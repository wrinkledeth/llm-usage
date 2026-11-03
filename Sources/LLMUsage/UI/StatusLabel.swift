import LLMUsageCore
import SwiftUI

/// The menu-bar item: per provider, its logo with 5h usage stacked over weekly usage.
struct StatusLabel: View {
    let store: UsageStore
    let onSizeChange: (CGSize) -> Void

    var body: some View {
        HStack(spacing: 6) {
            ForEach(store.visibleProviders) { provider in
                let status = store.status(provider)
                HStack(spacing: 1.5) {
                    ProviderIconView(provider: provider)
                        .frame(width: 14, height: 14)
                    VStack(alignment: .leading, spacing: -1.5) {
                        Text(UsageFormat.percent(status.snapshot?.session?.percent))
                        Text(UsageFormat.percent(status.snapshot?.weekly?.percent))
                    }
                    .font(.system(size: 9.5).monospacedDigit())
                    .frame(minWidth: 22, alignment: .leading)
                }
                .opacity(status.isDimmed ? 0.55 : 1)
            }
        }
        .foregroundStyle(.primary)
        .padding(.horizontal, 2)
        .fixedSize()
        .onGeometryChange(for: CGSize.self) { $0.size } action: { onSizeChange($0) }
    }
}
