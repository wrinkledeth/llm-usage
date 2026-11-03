import Foundation

/// OpenCode Go subscription usage: 5h rolling, weekly and monthly spend caps.
///
/// Uses the same API key Pi or OpenCode hold for the `opencode-go` provider. Lookup order:
/// `OPENCODE_API_KEY`, Pi's auth store, then OpenCode's auth store.
public enum OpenCodeUsage {
    static let usageURL = URL(string: "https://opencode.ai/zen/go/v1/usage")!
    static let providerKey = "opencode-go"

    public static func load() async throws -> UsageSnapshot {
        let key = try apiKey()
        var request = URLRequest(url: usageURL)
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, status) = try await HTTP.send(request)
        switch status {
        case 200: return try map(JSONValue.parse(data))
        case 401, 403: throw UsageError.unauthorized("OpenCode Go key rejected (HTTP \(status))")
        default: throw UsageError.failed("OpenCode Go usage HTTP \(status)")
        }
    }

    public static func authFiles(env: [String: String] = ProcessInfo.processInfo.environment) -> [URL] {
        let home = URL(fileURLWithPath: env["HOME"] ?? NSHomeDirectory())
        let pi = env["PI_CODING_AGENT_DIR"].map { URL(fileURLWithPath: $0) }
            ?? home.appending(path: ".pi/agent")
        let data = env["XDG_DATA_HOME"].map { URL(fileURLWithPath: $0) }
            ?? home.appending(path: ".local/share")
        return [pi.appending(path: "auth.json"), data.appending(path: "opencode/auth.json")]
    }

    public static func apiKey(env: [String: String] = ProcessInfo.processInfo.environment) throws -> String {
        if let key = env["OPENCODE_API_KEY"]?.trimmingCharacters(in: .whitespacesAndNewlines), !key.isEmpty {
            return key
        }
        for file in authFiles(env: env) {
            guard let data = try? Data(contentsOf: file), let json = try? JSONValue.parse(data),
                  let key = parseAPIKey(json) else { continue }
            return key
        }
        throw UsageError.notConfigured("No OpenCode Go API key")
    }

    /// The `opencode-go` API key from a Pi (`api_key`) or OpenCode (`api`) auth.json.
    public static func parseAPIKey(_ json: JSONValue) -> String? {
        guard let entry = json[providerKey], entry.object != nil else { return nil }
        if let type = entry["type"]?.string, !["api", "api_key"].contains(type) { return nil }
        return entry["key"]?.nonEmptyString ?? entry["apiKey"]?.nonEmptyString
    }

    public static func map(_ json: JSONValue, now: Date = .now) throws -> UsageSnapshot {
        guard let usage = json["usage"], let rolling = usage["rolling"], rolling.object != nil else {
            throw UsageError.failed("OpenCode Go usage response missing fields")
        }
        return UsageSnapshot(
            provider: .opencode,
            session: window(rolling, seconds: 5 * 3_600),
            weekly: usage["weekly"].flatMap { window($0, seconds: 7 * 86_400) },
            monthly: usage["monthly"].flatMap { window($0, seconds: nil) },
            fetchedAt: now
        )
    }

    static func window(_ raw: JSONValue, seconds: Int?) -> UsageWindow? {
        guard raw.object != nil else { return nil }
        var percent = raw["percent"]?.double
        if percent == nil, let used = raw["used"]?.double, let limit = raw["limit"]?.double, limit > 0 {
            percent = used / limit * 100
        }
        return UsageWindow(percent: percent, resetsAt: ISODate.parse(raw["resetsAt"]?.string), windowSeconds: seconds)
    }
}
