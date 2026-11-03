import Foundation

public struct ProcessResult: Sendable {
    public var status: Int32
    public var stdout: String
    public var stderr: String
    public var timedOut: Bool
}

/// Runs the provider CLIs (claude, codex). Apps launched by launchd get a bare PATH, so the
/// usual install locations are added explicitly.
public enum ProcessRunner {
    public static func environment(_ base: [String: String] = ProcessInfo.processInfo.environment) -> [String: String] {
        var env = base
        let home = env["HOME"] ?? NSHomeDirectory()
        let extra = ["/opt/homebrew/bin", "\(home)/.local/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        let existing = (env["PATH"] ?? "").split(separator: ":").map(String.init)
        env["PATH"] = (existing + extra.filter { !existing.contains($0) }).joined(separator: ":")
        let user = NSUserName()
        if env["USER"] == nil { env["USER"] = user }
        if env["LOGNAME"] == nil { env["LOGNAME"] = user }
        return env
    }

    /// Resolve `name` via an override variable (path or name), then PATH.
    public static func findExecutable(_ name: String, overrideVariable: String, env: [String: String]) -> String? {
        let fm = FileManager.default
        let override = env[overrideVariable]?.trimmingCharacters(in: .whitespaces) ?? ""
        let target = override.isEmpty ? name : override
        if target.contains("/") {
            return fm.isExecutableFile(atPath: target) ? target : nil
        }
        for dir in (env["PATH"] ?? "").split(separator: ":") {
            let candidate = "\(dir)/\(target)"
            if fm.isExecutableFile(atPath: candidate) { return candidate }
        }
        return nil
    }

    /// Run to completion (stdin closed), killing the process after `timeout` seconds.
    public static func run(
        _ executable: String,
        _ arguments: [String],
        env: [String: String],
        timeout: TimeInterval
    ) async throws -> ProcessResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.environment = env
        process.currentDirectoryURL = FileManager.default.temporaryDirectory
        let out = Pipe(), err = Pipe()
        process.standardOutput = out
        process.standardError = err
        process.standardInput = FileHandle.nullDevice

        do {
            try process.run()
        } catch {
            throw UsageError.failed("Couldn't run \((executable as NSString).lastPathComponent): \(error.localizedDescription)")
        }

        let running = process
        let deadline = Task.detached {
            try? await Task.sleep(for: .seconds(timeout))
            guard !Task.isCancelled, running.isRunning else { return false }
            running.terminate()
            return true
        }

        // Drain both pipes concurrently so neither can fill up and stall the child.
        async let stdoutData = Task.detached { out.fileHandleForReading.readDataToEndOfFile() }.value
        async let stderrData = Task.detached { err.fileHandleForReading.readDataToEndOfFile() }.value
        let (o, e) = await (stdoutData, stderrData)
        await Task.detached { running.waitUntilExit() }.value
        deadline.cancel()
        let timedOut = await deadline.value

        return ProcessResult(
            status: process.terminationStatus,
            stdout: String(decoding: o, as: UTF8.self),
            stderr: String(decoding: e, as: UTF8.self),
            timedOut: timedOut
        )
    }
}
