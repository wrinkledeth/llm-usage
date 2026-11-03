import Foundation

public struct CodexCredentials: Sendable, Equatable {
    public var accessToken: String
    public var refreshToken: String
    public var idToken: String?
    public var accountID: String?
    public var lastRefresh: Date?

    var needsRefresh: Bool {
        guard !refreshToken.isEmpty else { return false }
        guard let lastRefresh else { return true }
        return Date.now.timeIntervalSince(lastRefresh) > CodexUsage.refreshInterval
    }
}

/// Codex usage from ChatGPT's usage API using the Codex CLI's OAuth login (`~/.codex/auth.json`),
/// falling back to the CLI's `codex app-server` JSON-RPC.
public enum CodexUsage {
    static let refreshInterval: TimeInterval = 8 * 86_400
    static let defaultBaseURL = "https://chatgpt.com/backend-api/"
    static let refreshURL = URL(string: "https://auth.openai.com/oauth/token")!
    static let refreshClientID = "app_EMoamEEZ73f0CkXaXp7hrann"

    public static func load(env: [String: String] = ProcessInfo.processInfo.environment) async throws -> UsageSnapshot {
        let authFile = authFileURL(env: env)
        let processEnv = ProcessRunner.environment(env)
        let codex = ProcessRunner.findExecutable("codex", overrideVariable: "CODEX_CLI_PATH", env: processEnv)
        if !FileManager.default.fileExists(atPath: authFile.path), codex == nil {
            throw UsageError.notConfigured("Codex not set up")
        }

        let oauthError: Error
        do {
            return try await loadViaOAuth(authFile: authFile, env: env)
        } catch {
            oauthError = error
        }
        guard let codex else { throw oauthError }
        do {
            let limits = try await CodexAppServer.readRateLimits(executable: codex, env: processEnv)
            return try mapRPC(limits)
        } catch {
            throw UsageError.failed("\(oauthError.shortMessage); app-server fallback: \(error.shortMessage)")
        }
    }

    /// The fallback path on its own (for `--print --codex-app-server`).
    public static func loadViaAppServer(env: [String: String] = ProcessInfo.processInfo.environment) async throws -> UsageSnapshot {
        let processEnv = ProcessRunner.environment(env)
        guard let codex = ProcessRunner.findExecutable("codex", overrideVariable: "CODEX_CLI_PATH", env: processEnv) else {
            throw UsageError.notConfigured("codex CLI not found")
        }
        return try mapRPC(await CodexAppServer.readRateLimits(executable: codex, env: processEnv))
    }

    static func loadViaOAuth(authFile: URL, env: [String: String]) async throws -> UsageSnapshot {
        guard let data = try? Data(contentsOf: authFile) else {
            throw UsageError.failed("Codex auth.json not found. Run `codex login`.")
        }
        var credentials = try parseAuth(data)
        if credentials.needsRefresh {
            credentials = try await refresh(credentials)
            try saveCredentials(credentials, to: authFile)
        }
        do {
            return try mapOAuth(await fetchUsage(credentials, env: env))
        } catch UsageError.unauthorized where !credentials.refreshToken.isEmpty {
            credentials = try await refresh(credentials)
            try saveCredentials(credentials, to: authFile)
            return try mapOAuth(await fetchUsage(credentials, env: env))
        }
    }

    // MARK: Credentials

    public static func authFileURL(env: [String: String]) -> URL {
        if let home = env["CODEX_HOME"]?.trimmingCharacters(in: .whitespaces), !home.isEmpty {
            return URL(fileURLWithPath: (home as NSString).expandingTildeInPath).appending(path: "auth.json")
        }
        return URL(fileURLWithPath: env["HOME"] ?? NSHomeDirectory()).appending(path: ".codex/auth.json")
    }

    public static func parseAuth(_ data: Data) throws -> CodexCredentials {
        guard let json = try? JSONValue.parse(data) else { throw UsageError.failed("Invalid Codex auth.json") }
        if let apiKey = json["OPENAI_API_KEY"]?.nonEmptyString {
            return CodexCredentials(accessToken: apiKey, refreshToken: "", idToken: nil, accountID: nil, lastRefresh: nil)
        }
        func token(_ keys: String...) -> String? {
            keys.lazy.compactMap { json["tokens"]?[$0]?.nonEmptyString }.first
        }
        guard let access = token("access_token", "accessToken") else {
            throw UsageError.failed("Codex auth.json has no tokens. Run `codex login`.")
        }
        return CodexCredentials(
            accessToken: access,
            refreshToken: token("refresh_token", "refreshToken") ?? "",
            idToken: token("id_token", "idToken"),
            accountID: token("account_id", "accountId"),
            lastRefresh: ISODate.parse(json["last_refresh"]?.string)
        )
    }

    /// Write refreshed tokens back, keeping any other fields the CLI stores. The file stays 0600.
    public static func saveCredentials(_ credentials: CodexCredentials, to file: URL, now: Date = .now) throws {
        var root = (try? Data(contentsOf: file))
            .flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
        var tokens = root["tokens"] as? [String: Any] ?? [:]
        tokens["access_token"] = credentials.accessToken
        tokens["refresh_token"] = credentials.refreshToken
        if let id = credentials.idToken { tokens["id_token"] = id }
        if let account = credentials.accountID { tokens["account_id"] = account }
        root["tokens"] = tokens
        root["last_refresh"] = ISODate.format(now)

        var data = try JSONSerialization.data(withJSONObject: root, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
        data.append(0x0A)
        try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
    }

    static func refresh(_ credentials: CodexCredentials) async throws -> CodexCredentials {
        guard !credentials.refreshToken.isEmpty else { return credentials }
        var request = URLRequest(url: refreshURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "client_id": refreshClientID,
            "grant_type": "refresh_token",
            "refresh_token": credentials.refreshToken,
        ])
        let (data, status) = try await HTTP.send(request)
        guard status == 200 else {
            if status == 401 { throw UsageError.unauthorized("Codex login expired. Run `codex login`.") }
            throw UsageError.failed("Codex token refresh HTTP \(status)")
        }
        let json = try JSONValue.parse(data)
        var updated = credentials
        updated.accessToken = json["access_token"]?.nonEmptyString ?? credentials.accessToken
        updated.refreshToken = json["refresh_token"]?.nonEmptyString ?? credentials.refreshToken
        updated.idToken = json["id_token"]?.nonEmptyString ?? credentials.idToken
        updated.lastRefresh = .now
        return updated
    }

    // MARK: OAuth usage API

    /// `chatgpt_base_url` from Codex's config.toml decides between ChatGPT and Codex usage paths.
    public static func usageURL(env: [String: String], configContents: String? = nil) -> URL {
        let config = configContents ?? (try? String(
            contentsOf: authFileURL(env: env).deletingLastPathComponent().appending(path: "config.toml"),
            encoding: .utf8))
        var base = config.flatMap(parseBaseURL) ?? defaultBaseURL
        while base.hasSuffix("/") { base.removeLast() }
        if (base.hasPrefix("https://chatgpt.com") || base.hasPrefix("https://chat.openai.com")), !base.contains("/backend-api") {
            base += "/backend-api"
        }
        let path = base.contains("/backend-api") ? "/wham/usage" : "/api/codex/usage"
        return URL(string: base + path)!
    }

    static func parseBaseURL(_ toml: String) -> String? {
        for raw in toml.split(separator: "\n") {
            let line = raw.split(separator: "#", maxSplits: 1).first.map(String.init) ?? ""
            let parts = line.split(separator: "=", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
            guard parts.count == 2, parts[0] == "chatgpt_base_url" else { continue }
            let value = parts[1].trimmingCharacters(in: CharacterSet(charactersIn: "\"'")).trimmingCharacters(in: .whitespaces)
            return value.isEmpty ? nil : value
        }
        return nil
    }

    static func fetchUsage(_ credentials: CodexCredentials, env: [String: String]) async throws -> JSONValue {
        var request = URLRequest(url: usageURL(env: env))
        request.setValue("Bearer \(credentials.accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let account = credentials.accountID { request.setValue(account, forHTTPHeaderField: "ChatGPT-Account-Id") }
        let (data, status) = try await HTTP.send(request)
        switch status {
        case 200: return try JSONValue.parse(data)
        case 401, 403: throw UsageError.unauthorized("Codex login expired or invalid")
        default: throw UsageError.failed("Codex usage API HTTP \(status): \(HTTP.bodySnippet(data))")
        }
    }

    public static func mapOAuth(_ json: JSONValue, now: Date = .now) throws -> UsageSnapshot {
        guard let limits = json["rate_limit"], limits.object != nil else {
            throw UsageError.failed("Codex usage response has no rate limits")
        }
        func window(_ raw: JSONValue?) -> UsageWindow? {
            guard let raw, raw.object != nil else { return nil }
            return UsageWindow(percent: raw["used_percent"]?.double,
                               resetsAt: raw["reset_at"]?.double.map { Date(timeIntervalSince1970: $0) },
                               windowSeconds: raw["limit_window_seconds"]?.int)
        }
        let (session, weekly) = splitWindows([window(limits["primary_window"]), window(limits["secondary_window"])])
        guard session != nil || weekly != nil else { throw UsageError.failed("Codex usage response has no rate limits") }
        let c = json["credits"]
        return UsageSnapshot(provider: .codex, session: session, weekly: weekly,
                             credits: credits(has: c?["has_credits"], unlimited: c?["unlimited"], balance: c?["balance"]),
                             fetchedAt: now)
    }

    public static func mapRPC(_ json: JSONValue, now: Date = .now) throws -> UsageSnapshot {
        // Prefer the canonical "codex" bucket; older servers only send `rateLimits`.
        let limits = json["rateLimitsByLimitId"]?["codex"].flatMap { $0.object != nil ? $0 : nil } ?? json["rateLimits"]
        guard let limits, limits.object != nil else { throw UsageError.failed("Codex app-server returned no rate limits") }
        func window(_ raw: JSONValue?) -> UsageWindow? {
            guard let raw, raw.object != nil else { return nil }
            return UsageWindow(percent: raw["usedPercent"]?.double,
                               resetsAt: raw["resetsAt"]?.double.map { Date(timeIntervalSince1970: $0) },
                               windowSeconds: raw["windowDurationMins"]?.int.map { $0 * 60 })
        }
        let (session, weekly) = splitWindows([window(limits["primary"]), window(limits["secondary"])])
        guard session != nil || weekly != nil else { throw UsageError.failed("Codex app-server returned no rate limits") }
        let c = limits["credits"]
        return UsageSnapshot(provider: .codex, session: session, weekly: weekly,
                             credits: credits(has: c?["hasCredits"], unlimited: c?["unlimited"], balance: c?["balance"]),
                             fetchedAt: now)
    }

    static func credits(has: JSONValue?, unlimited: JSONValue?, balance: JSONValue?) -> CodexCredits? {
        let amount = balance?.double
        let isUnlimited = unlimited?.isTruthy ?? false
        guard has?.isTruthy == true || isUnlimited || (amount ?? 0) > 0 else { return nil }
        return CodexCredits(balance: amount, unlimited: isUnlimited)
    }

    /// Sort the reported windows into (short session, long weekly) by duration.
    static func splitWindows(_ windows: [UsageWindow?]) -> (UsageWindow?, UsageWindow?) {
        let present = windows.compactMap { $0 }.filter { $0.percent != nil }
        let longThreshold = 8 * 3_600
        switch present.count {
        case 0:
            return (nil, nil)
        case 1:
            let only = present[0]
            return (only.windowSeconds ?? 0) > longThreshold ? (nil, only) : (only, nil)
        default:
            let known = present.filter { $0.windowSeconds != nil }
            let unknown = present.filter { $0.windowSeconds == nil }
            if known.count >= 2 {
                let ordered = known.sorted { $0.windowSeconds! < $1.windowSeconds! }
                return (ordered.first, ordered.last)
            }
            if known.count == 1 {
                return known[0].windowSeconds! <= longThreshold ? (known[0], unknown[0]) : (unknown[0], known[0])
            }
            return (present.first, present.last)
        }
    }
}
