import Foundation

/// Claude subscription usage from the Claude Code CLI's `/usage` command (costs no tokens).
public enum ClaudeUsage {
    static let arguments = ["-p", "--output-format", "json", "--tools", "", "--no-session-persistence", "/usage"]

    public static func load() async throws -> UsageSnapshot {
        let env = ProcessRunner.environment()
        guard let claude = ProcessRunner.findExecutable("claude", overrideVariable: "CLAUDE_CLI_PATH", env: env) else {
            throw UsageError.notConfigured("Claude Code CLI not found")
        }
        let result = try await ProcessRunner.run(claude, arguments, env: env, timeout: 30)
        if result.timedOut { throw UsageError.failed("Claude CLI timed out") }
        guard result.status == 0 else {
            let detail = (result.stderr.isEmpty ? result.stdout : result.stderr)
                .split(separator: "\n").last.map(String.init) ?? "exit status \(result.status)"
            throw UsageError.failed("Claude CLI: \(detail.prefix(160))")
        }
        return try parseCLIOutput(result.stdout)
    }

    /// The CLI prints one JSON object per line; the last one carries the `/usage` text.
    public static func parseCLIOutput(_ stdout: String, now: Date = .now) throws -> UsageSnapshot {
        let payload = stdout.split(separator: "\n").reversed().lazy
            .compactMap { try? JSONValue.parse(String($0)) }
            .first { $0.object != nil }
        guard let payload else { throw UsageError.failed("Claude CLI returned invalid JSON") }
        if payload["is_error"]?.isTruthy == true {
            throw UsageError.failed(payload["result"]?.string ?? "Claude CLI reported an error")
        }
        guard let text = payload["result"]?.string else {
            throw UsageError.failed("Claude CLI returned no usage text")
        }
        if text.hasPrefix("Total cost:") {
            throw UsageError.failed("Claude CLI is not using a subscription (API key login)")
        }
        return try parse(text, now: now)
    }

    public static func parse(_ text: String, now: Date = .now) throws -> UsageSnapshot {
        let sessionLine = #/^Current session:\s*(?<percent>\d+(?:\.\d+)?)% used(?:\s*(?:·|-)\s*resets\s+(?<reset>.+))?$/#
        // "Current week (all models)" only; per-model weeks like "(Fable)" are skipped.
        let weekLine = #/^Current week(?: \(all models\))?:\s*(?<percent>\d+(?:\.\d+)?)% used(?:\s*(?:·|-)\s*resets\s+(?<reset>.+))?$/#

        var session: UsageWindow?
        var weekly: UsageWindow?
        for raw in text.split(separator: "\n") {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if let m = line.wholeMatch(of: sessionLine) {
                session = UsageWindow(percent: Double(m.percent), resetsAt: m.reset.flatMap { parseReset(String($0), now: now) },
                                      windowSeconds: 5 * 3_600)
            } else if let m = line.wholeMatch(of: weekLine) {
                weekly = UsageWindow(percent: Double(m.percent), resetsAt: m.reset.flatMap { parseReset(String($0), now: now) },
                                     windowSeconds: 7 * 86_400)
            }
        }
        guard session != nil || weekly != nil else {
            throw UsageError.failed("Unexpected Claude /usage format")
        }
        return UsageSnapshot(provider: .claude, session: session, weekly: weekly, fetchedAt: now)
    }

    /// "Nov 3 at 4:10pm (America/New_York)", "Dec 31, 2026 at 11pm (UTC)", "Tomorrow at 6am (UTC)".
    static func parseReset(_ value: String, now: Date) -> Date? {
        let pattern = #/^(?<date>[A-Za-z]{3} \d{1,2}(?:,? \d{4})?|Today|Tomorrow) at (?<hour>\d{1,2})(?::(?<minute>\d{2}))?(?<ampm>[ap]m) \((?<tz>[^)]+)\)$/#
            .ignoresCase()
        guard let m = value.trimmingCharacters(in: .whitespaces).wholeMatch(of: pattern),
              let tz = TimeZone(identifier: String(m.tz)),
              var hour = Int(m.hour), (1...12).contains(hour)
        else { return nil }
        let minute = m.minute.flatMap { Int($0) } ?? 0
        let pm = m.ampm.lowercased() == "pm"
        hour = (hour % 12) + (pm ? 12 : 0)

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = tz
        let today = calendar.dateComponents([.year, .month, .day], from: now)
        var components = DateComponents(timeZone: tz, hour: hour, minute: minute)

        switch m.date.lowercased() {
        case "today", "tomorrow":
            let base = calendar.date(from: today)!
            let day = m.date.lowercased() == "tomorrow" ? calendar.date(byAdding: .day, value: 1, to: base)! : base
            let parts = calendar.dateComponents([.year, .month, .day], from: day)
            (components.year, components.month, components.day) = (parts.year, parts.month, parts.day)
        default:
            let pieces = m.date.replacingOccurrences(of: ",", with: "").split(separator: " ")
            let months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
            guard let month = months.firstIndex(of: pieces[0].lowercased()), let day = Int(pieces[1]) else { return nil }
            components.month = month + 1
            components.day = day
            if pieces.count == 3, let year = Int(pieces[2]) {
                components.year = year
            } else {
                // No year: this year, unless that's already in the past (e.g. "Jan 2" seen on Dec 31).
                components.year = today.year
                if let candidate = calendar.date(from: components),
                   candidate < calendar.date(byAdding: .day, value: -1, to: calendar.date(from: today)!)! {
                    components.year = today.year! + 1
                }
            }
        }
        return calendar.date(from: components)
    }
}
