import Foundation
import Testing
@testable import LLMUsageCore

struct OpenCodeUsageTests {
    @Test func parsesPiAndOpenCodeKeys() throws {
        #expect(OpenCodeUsage.parseAPIKey(try .parse(#"{"opencode-go": {"type": "api_key", "key": " sk-pi "}}"#)) == "sk-pi")
        #expect(OpenCodeUsage.parseAPIKey(try .parse(#"{"opencode-go": {"type": "api", "key": "sk-oc"}}"#)) == "sk-oc")
        #expect(OpenCodeUsage.parseAPIKey(try .parse(#"{"openai": {"type": "api_key", "key": "x"}}"#)) == nil)
        #expect(OpenCodeUsage.parseAPIKey(try .parse(#"{"opencode-go": {"type": "oauth", "access": "x"}}"#)) == nil)
    }

    @Test func keyLookupOrder() throws {
        let home = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: home) }
        func write(_ rel: String, _ json: String) throws {
            let url = home.appending(path: rel)
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data(json.utf8).write(to: url)
        }
        let env = ["HOME": home.path]
        #expect(throws: UsageError.self) { try OpenCodeUsage.apiKey(env: env) }

        try write(".pi/agent/auth.json", "{not json")
        try write(".local/share/opencode/auth.json", #"{"opencode-go": {"type": "api", "key": "from-oc"}}"#)
        #expect(try OpenCodeUsage.apiKey(env: env) == "from-oc")

        try write(".pi/agent/auth.json", #"{"opencode-go": {"type": "api_key", "key": "from-pi"}}"#)
        #expect(try OpenCodeUsage.apiKey(env: env) == "from-pi")
        #expect(try OpenCodeUsage.apiKey(env: env.merging(["OPENCODE_API_KEY": "from-env"]) { $1 }) == "from-env")
    }

    @Test func mapsThreeWindows() throws {
        let json = try JSONValue.parse("""
            {"usage": {"rolling": {"status": "ok", "percent": 12.5, "resetsAt": "2026-11-04T01:09:32.000Z"},
                       "weekly": {"status": "ok", "percent": 40, "resetsAt": "2026-11-09T00:00:00.000Z"},
                       "monthly": {"status": "ok", "percent": 3, "resetsAt": "2026-12-03T19:57:07.000Z"}}}
            """)
        let snap = try OpenCodeUsage.map(json)
        #expect(snap.provider == .opencode)
        #expect(snap.session?.percent == 12.5)
        #expect(snap.session?.windowSeconds == 5 * 3_600)
        #expect(snap.session?.resetsAt == ISODate.parse("2026-11-04T01:09:32Z"))
        #expect(snap.weekly?.percent == 40)
        #expect(snap.monthly?.percent == 3)
    }

    @Test func usedOverLimitFallbackAndMissingFields() throws {
        let snap = try OpenCodeUsage.map(try .parse(#"{"usage": {"rolling": {"used": 3, "limit": 12}}}"#))
        #expect(snap.session?.percent == 25)
        #expect(snap.weekly == nil && snap.monthly == nil)
        #expect(throws: UsageError.self) { try OpenCodeUsage.map(try .parse(#"{"usage": {}}"#)) }
    }
}
