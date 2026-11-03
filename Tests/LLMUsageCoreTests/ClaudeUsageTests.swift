import Foundation
import Testing
@testable import LLMUsageCore

struct ClaudeUsageTests {
    static let usageText = """
        You are currently using your subscription to power your Claude Code usage

        Current session: 26% used · resets Aug 11 at 11:19pm (America/New_York)
        Current week (all models): 80% used · resets Aug 12 at 4:59am (America/New_York)
        Current week (Fable): 3% used · resets Aug 12 at 4:59am (America/New_York)

        What's contributing to your usage?
        """

    static func date(_ y: Int, _ mo: Int, _ d: Int, _ h: Int, _ mi: Int, tz: String) -> Date {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: tz)!
        return cal.date(from: DateComponents(year: y, month: mo, day: d, hour: h, minute: mi))!
    }

    @Test func parsesSessionAndAllModelsWeek() throws {
        let now = Self.date(2026, 8, 11, 12, 0, tz: "America/New_York")
        let snap = try ClaudeUsage.parse(Self.usageText, now: now)
        #expect(snap.session?.percent == 26)
        #expect(snap.session?.windowSeconds == 5 * 3_600)
        #expect(snap.session?.resetsAt == Self.date(2026, 8, 11, 23, 19, tz: "America/New_York"))
        #expect(snap.weekly?.percent == 80)  // not the per-model "(Fable)" week
        #expect(snap.weekly?.resetsAt == Self.date(2026, 8, 12, 4, 59, tz: "America/New_York"))
    }

    @Test func handlesYearRolloverAndDashSeparator() throws {
        let text = """
            Current session: 1% used - resets Dec 31 at 11pm (UTC)
            Current week: 2% used - resets Jan 2 at 3am (UTC)
            """
        let now = Self.date(2026, 12, 31, 20, 0, tz: "UTC")
        let snap = try ClaudeUsage.parse(text, now: now)
        #expect(snap.session?.resetsAt == Self.date(2026, 12, 31, 23, 0, tz: "UTC"))
        #expect(snap.weekly?.resetsAt == Self.date(2027, 1, 2, 3, 0, tz: "UTC"))
    }

    @Test func parsesTodayTomorrowAndNoon() {
        let now = Self.date(2026, 3, 1, 9, 0, tz: "UTC")
        #expect(ClaudeUsage.parseReset("Today at 12pm (UTC)", now: now) == Self.date(2026, 3, 1, 12, 0, tz: "UTC"))
        #expect(ClaudeUsage.parseReset("Tomorrow at 12:30am (UTC)", now: now) == Self.date(2026, 3, 2, 0, 30, tz: "UTC"))
        #expect(ClaudeUsage.parseReset("Mar 9, 2027 at 1am (UTC)", now: now) == Self.date(2027, 3, 9, 1, 0, tz: "UTC"))
        #expect(ClaudeUsage.parseReset("whenever (Nowhere/Land)", now: now) == nil)
    }

    @Test func readsLastJSONLineOfCLIOutput() throws {
        let result = Self.usageText.replacingOccurrences(of: "\n", with: "\\n")
        let stdout = "noise\n{\"type\":\"result\",\"is_error\":false,\"result\":\"\(result)\"}\n"
        let snap = try ClaudeUsage.parseCLIOutput(stdout)
        #expect(snap.session?.percent == 26)
    }

    @Test func reportsCLIErrorsAndAPIKeyLogins() {
        #expect(throws: UsageError.failed("Not logged in")) {
            try ClaudeUsage.parseCLIOutput(#"{"is_error":true,"result":"Not logged in"}"#)
        }
        #expect(throws: UsageError.self) {
            try ClaudeUsage.parseCLIOutput(#"{"is_error":false,"result":"Total cost: $0.00"}"#)
        }
        #expect(throws: UsageError.self) { try ClaudeUsage.parse("nothing useful") }
    }
}
