import Foundation

/// The providers shown in the menu bar, in left-to-right order.
public enum ProviderID: String, CaseIterable, Sendable, Identifiable {
    case codex, claude, opencode

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .codex: "Codex"
        case .claude: "Claude"
        case .opencode: "OpenCode Go"
        }
    }

    /// Fetch this provider's current usage.
    public func loadUsage() async throws -> UsageSnapshot {
        switch self {
        case .codex: try await CodexUsage.load()
        case .claude: try await ClaudeUsage.load()
        case .opencode: try await OpenCodeUsage.load()
        }
    }
}

public struct UsageWindow: Sendable, Equatable {
    /// 0...100
    public var percent: Double?
    public var resetsAt: Date?
    public var windowSeconds: Int?

    public init(percent: Double?, resetsAt: Date? = nil, windowSeconds: Int? = nil) {
        self.percent = percent
        self.resetsAt = resetsAt
        self.windowSeconds = windowSeconds
    }
}

public struct CodexCredits: Sendable, Equatable {
    public var balance: Double?
    public var unlimited: Bool

    public init(balance: Double?, unlimited: Bool) {
        self.balance = balance
        self.unlimited = unlimited
    }
}

public struct UsageSnapshot: Sendable, Equatable {
    public var provider: ProviderID
    /// Short rolling window (5h).
    public var session: UsageWindow?
    public var weekly: UsageWindow?
    public var monthly: UsageWindow?
    public var credits: CodexCredits?
    public var fetchedAt: Date

    public init(
        provider: ProviderID,
        session: UsageWindow?,
        weekly: UsageWindow?,
        monthly: UsageWindow? = nil,
        credits: CodexCredits? = nil,
        fetchedAt: Date = .now
    ) {
        self.provider = provider
        self.session = session
        self.weekly = weekly
        self.monthly = monthly
        self.credits = credits
        self.fetchedAt = fetchedAt
    }

    public var hasAnyUsage: Bool {
        session?.percent != nil || weekly?.percent != nil
    }
}

public enum UsageError: Error, Equatable, Sendable, CustomStringConvertible {
    /// The provider isn't set up on this machine (no CLI, no login); it is hidden, not shown as an error.
    case notConfigured(String)
    case unauthorized(String)
    case failed(String)

    public var description: String {
        switch self {
        case .notConfigured(let m), .unauthorized(let m), .failed(let m): m
        }
    }
}

extension Error {
    /// One-line message for the UI.
    public var shortMessage: String {
        let text = (self as? UsageError)?.description ?? localizedDescription
        let line = text.split(separator: "\n").first.map(String.init) ?? text
        return line.count > 160 ? String(line.prefix(160)) + "…" : line
    }
}
