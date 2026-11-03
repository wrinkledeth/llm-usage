import Foundation
import Testing
@testable import LLMUsageCore

struct CodexUsageTests {
    @Test func parsesSnakeCaseTokens() throws {
        let creds = try CodexUsage.parseAuth(Data("""
            {"tokens": {"access_token": "a", "refresh_token": "r", "id_token": "i", "account_id": "acct"},
             "last_refresh": "2025-12-20T12:34:56.123456Z"}
            """.utf8))
        #expect(creds.accessToken == "a")
        #expect(creds.refreshToken == "r")
        #expect(creds.idToken == "i")
        #expect(creds.accountID == "acct")
        #expect(creds.lastRefresh == ISODate.parse("2025-12-20T12:34:56Z"))
    }

    @Test func parsesCamelCaseTokensAndAPIKey() throws {
        let camel = try CodexUsage.parseAuth(Data(#"{"tokens": {"accessToken": "a", "refreshToken": "r", "accountId": "x"}}"#.utf8))
        #expect(camel.accessToken == "a" && camel.refreshToken == "r" && camel.accountID == "x")
        #expect(camel.needsRefresh)  // no last_refresh recorded

        let key = try CodexUsage.parseAuth(Data(#"{"OPENAI_API_KEY": "sk-1"}"#.utf8))
        #expect(key.accessToken == "sk-1" && !key.needsRefresh)

        #expect(throws: UsageError.self) { try CodexUsage.parseAuth(Data("{}".utf8)) }
    }

    @Test func usageURLFollowsConfig() {
        let env = ["HOME": "/nonexistent"]
        #expect(CodexUsage.usageURL(env: env, configContents: "").absoluteString == "https://chatgpt.com/backend-api/wham/usage")
        #expect(CodexUsage.usageURL(env: env, configContents: #"chatgpt_base_url = "https://chatgpt.com/""#).absoluteString
            == "https://chatgpt.com/backend-api/wham/usage")
        #expect(CodexUsage.usageURL(env: env, configContents: "chatgpt_base_url = 'https://proxy.example/' # mine").absoluteString
            == "https://proxy.example/api/codex/usage")
    }

    @Test func appServerUsesSupportedApprovalFlag() {
        // codex 0.163 rejects `-a untrusted`; the fallback silently failed with it.
        #expect(CodexAppServer.arguments == ["-s", "read-only", "-a", "never", "app-server"])
    }

    static func window(_ percent: Double, _ seconds: Int?) -> JSONValue {
        var o: [String: JSONValue] = ["used_percent": .number(percent), "reset_at": .number(1_766_948_068)]
        if let seconds { o["limit_window_seconds"] = .number(Double(seconds)) }
        return .object(o)
    }

    static func oauth(_ primary: JSONValue, _ secondary: JSONValue, credits: JSONValue = .null) -> JSONValue {
        .object(["rate_limit": .object(["primary_window": primary, "secondary_window": secondary]), "credits": credits])
    }

    @Test func splitsSessionAndWeeklyWithCredits() throws {
        let credits: JSONValue = .object(["has_credits": .bool(true), "unlimited": .bool(false), "balance": .string("150.0")])
        let snap = try CodexUsage.mapOAuth(Self.oauth(Self.window(22, 18_000), Self.window(43, 604_800), credits: credits))
        #expect(snap.session?.percent == 22)
        #expect(snap.weekly?.percent == 43)
        #expect(snap.session?.resetsAt == Date(timeIntervalSince1970: 1_766_948_068))
        #expect(snap.credits == CodexCredits(balance: 150, unlimited: false))
    }

    @Test func singleLongWindowIsWeekly() throws {
        for seconds in [604_800, 5 * 86_400] {
            let snap = try CodexUsage.mapOAuth(Self.oauth(Self.window(7, seconds), .null))
            #expect(snap.session == nil)
            #expect(snap.weekly?.percent == 7)
        }
    }

    @Test func ordersWindowsByDuration() throws {
        let reversed = try CodexUsage.mapOAuth(Self.oauth(Self.window(43, 604_800), Self.window(22, 18_000)))
        #expect(reversed.session?.percent == 22 && reversed.weekly?.percent == 43)

        let missing = try CodexUsage.mapOAuth(Self.oauth(Self.window(22, 18_000), Self.window(43, nil)))
        #expect(missing.session?.percent == 22 && missing.weekly?.percent == 43)
    }

    @Test func rpcPrefersCanonicalCodexBucket() throws {
        let json = try JSONValue.parse("""
            {"rateLimits": {"primary": {"usedPercent": 91, "windowDurationMins": 300},
                            "secondary": {"usedPercent": 92, "windowDurationMins": 10080}},
             "rateLimitsByLimitId": {
                "codex": {"primary": {"usedPercent": 31, "windowDurationMins": 300},
                          "secondary": {"usedPercent": 42, "windowDurationMins": 10080},
                          "credits": {"hasCredits": false, "unlimited": true}},
                "other": {"primary": {"usedPercent": 77, "windowDurationMins": 60}}}}
            """)
        let snap = try CodexUsage.mapRPC(json)
        #expect(snap.session?.percent == 31)
        #expect(snap.weekly?.percent == 42)
        #expect(snap.weekly?.windowSeconds == 10_080 * 60)
        #expect(snap.credits?.unlimited == true)
    }

    @Test func saveKeepsUnknownFieldsAndPrivatePermissions() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        let file = dir.appending(path: "auth.json")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try Data(#"{"auth_mode": "chatgpt", "tokens": {"access_token": "old", "extra": "keep"}}"#.utf8).write(to: file)

        let creds = CodexCredentials(accessToken: "new", refreshToken: "r2", idToken: nil, accountID: "acct", lastRefresh: nil)
        try CodexUsage.saveCredentials(creds, to: file)

        let json = try JSONValue.parse(Data(contentsOf: file))
        #expect(json["auth_mode"]?.string == "chatgpt")
        #expect(json["tokens"]?["extra"]?.string == "keep")
        #expect(json["tokens"]?["access_token"]?.string == "new")
        #expect(json["tokens"]?["account_id"]?.string == "acct")
        #expect(ISODate.parse(json["last_refresh"]?.string) != nil)
        let perms = try FileManager.default.attributesOfItem(atPath: file.path)[.posixPermissions] as? Int
        #expect(perms == 0o600)
    }
}
