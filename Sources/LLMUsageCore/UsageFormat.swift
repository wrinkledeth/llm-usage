import Foundation

public enum UsageFormat {
    /// "42%", or "--" when unknown.
    public static func percent(_ value: Double?) -> String {
        guard let value else { return "--" }
        return "\(Int(value.rounded()))%"
    }

    /// Time left until `date`: "1d 7h" for long waits, "2h 03m" otherwise.
    public static func countdown(to date: Date?, now: Date = .now) -> String? {
        guard let date else { return nil }
        let total = max(0, Int(date.timeIntervalSince(now)))
        let days = total / 86_400
        let hours = (total % 86_400) / 3_600
        let minutes = (total % 3_600) / 60
        if days > 0 { return "\(days)d \(hours)h" }
        return "\(hours)h " + String(format: "%02dm", minutes)
    }

    /// "5h" / "7d" / "30m" from a window length, else `fallback`.
    public static func windowLabel(_ window: UsageWindow?, fallback: String) -> String {
        guard let seconds = window?.windowSeconds, seconds > 0 else { return fallback }
        let value: Double
        let suffix: String
        switch seconds {
        case 86_400...: (value, suffix) = (Double(seconds) / 86_400, "d")
        case 3_600...: (value, suffix) = (Double(seconds) / 3_600, "h")
        case 60...: (value, suffix) = (Double(seconds) / 60, "m")
        default: return fallback
        }
        if value == value.rounded() { return "\(Int(value))\(suffix)" }
        return String(format: "%.1f", value) + suffix
    }
}
