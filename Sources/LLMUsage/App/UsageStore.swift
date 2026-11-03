import AppKit
import LLMUsageCore
import Observation

/// What the UI shows for one provider.
struct ProviderStatus: Equatable {
    /// Last good reading; kept (dimmed) when a later refresh fails.
    var snapshot: UsageSnapshot?
    var error: String?
    /// Not set up on this machine (no CLI / login): left out of the UI entirely.
    var isHidden: Bool

    var isDimmed: Bool { error != nil || snapshot?.hasAnyUsage != true }
}

@MainActor
@Observable
final class UsageStore {
    static let refreshInterval: Duration = .seconds(300)

    private(set) var statuses: [ProviderID: ProviderStatus]
    private(set) var isRefreshing = false
    private(set) var lastRefresh: Date?
    @ObservationIgnored private var loop: Task<Void, Never>?
    @ObservationIgnored private var wakeObserver: NSObjectProtocol?

    init() {
        // OpenCode Go starts hidden so machines without a Go key never flash its slot.
        statuses = Dictionary(uniqueKeysWithValues: ProviderID.allCases.map {
            ($0, ProviderStatus(isHidden: $0 == .opencode))
        })
    }

    var visibleProviders: [ProviderID] {
        ProviderID.allCases.filter { statuses[$0]?.isHidden == false }
    }

    func status(_ provider: ProviderID) -> ProviderStatus {
        statuses[provider] ?? ProviderStatus(isHidden: true)
    }

    /// Refresh now, then every five minutes and after the Mac wakes.
    func start() {
        loop?.cancel()
        loop = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(for: Self.refreshInterval)
            }
        }
        wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                try? await Task.sleep(for: .seconds(5))  // let the network come back
                await self?.refresh()
            }
        }
    }

    /// Refresh if the data is older than `age` (e.g. when the panel opens).
    func refreshIfStale(olderThan age: TimeInterval = 60) {
        guard let lastRefresh, Date.now.timeIntervalSince(lastRefresh) < age else {
            Task { await refresh() }
            return
        }
    }

    func refresh() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        defer {
            isRefreshing = false
            lastRefresh = .now
        }
        // Providers load in parallel; each result is applied as soon as it arrives.
        await withTaskGroup(of: (ProviderID, Result<UsageSnapshot, any Error>).self) { group in
            for provider in ProviderID.allCases {
                group.addTask {
                    do { return (provider, .success(try await provider.loadUsage())) }
                    catch { return (provider, .failure(error)) }
                }
            }
            for await (provider, result) in group {
                apply(result, to: provider)
            }
        }
    }

    private func apply(_ result: Result<UsageSnapshot, any Error>, to provider: ProviderID) {
        var status = self.status(provider)
        switch result {
        case .success(let snapshot):
            status = ProviderStatus(snapshot: snapshot, error: nil, isHidden: false)
        case .failure(UsageError.notConfigured):
            status = ProviderStatus(snapshot: nil, error: nil, isHidden: true)
        case .failure(let error):
            let message = error.shortMessage
            if status.error != message { Log.write("\(provider.displayName): \(message)") }
            status.error = message
            status.isHidden = false
        }
        statuses[provider] = status
    }
}
