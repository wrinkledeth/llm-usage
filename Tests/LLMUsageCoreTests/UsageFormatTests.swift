import Foundation
import Testing
@testable import LLMUsageCore

struct UsageFormatTests {
    @Test func percent() {
        #expect(UsageFormat.percent(nil) == "--")
        #expect(UsageFormat.percent(42.4) == "42%")
        #expect(UsageFormat.percent(0) == "0%")
    }

    @Test func countdown() {
        let now = Date(timeIntervalSince1970: 0)
        #expect(UsageFormat.countdown(to: nil, now: now) == nil)
        #expect(UsageFormat.countdown(to: now.addingTimeInterval(2 * 3_600 + 3 * 60), now: now) == "2h 03m")
        #expect(UsageFormat.countdown(to: now.addingTimeInterval(86_400 + 7 * 3_600 + 59), now: now) == "1d 7h")
        #expect(UsageFormat.countdown(to: now.addingTimeInterval(-60), now: now) == "0h 00m")
    }

    @Test func windowLabel() {
        #expect(UsageFormat.windowLabel(nil, fallback: "5h") == "5h")
        #expect(UsageFormat.windowLabel(UsageWindow(percent: 1, windowSeconds: 18_000), fallback: "x") == "5h")
        #expect(UsageFormat.windowLabel(UsageWindow(percent: 1, windowSeconds: 604_800), fallback: "x") == "7d")
        #expect(UsageFormat.windowLabel(UsageWindow(percent: 1, windowSeconds: 5_400), fallback: "x") == "1.5h")
    }

    @Test func isoDates() {
        #expect(ISODate.parse("2026-11-04T01:09:32.000Z") == ISODate.parse("2026-11-04T01:09:32Z"))
        #expect(ISODate.parse("2026-11-04T03:09:32.123456789+02:00") == ISODate.parse("2026-11-04T01:09:32Z"))
        #expect(ISODate.parse("nope") == nil)
        let now = Date(timeIntervalSince1970: 1_800_000_000)
        #expect(ISODate.parse(ISODate.format(now)) == now)
    }
}
