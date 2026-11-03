// LLM Usage launcher: a tiny native app around the Python menu-bar code.
//
// The Python sources ship in Contents/Resources/app (staged by macapp.conf PREBUILD).
// On launch this keeps a private venv in sync with uv.lock (only when the lock file
// changes), then runs `python claude_bar.py` — the Python process draws the menu-bar
// item. The launcher has no UI of its own: it quits when Python exits normally (its
// Quit menu item), restarts it after a crash, and stops it when the app is quit.
// It also registers itself as a login item (replacing the old install.sh LaunchAgent).

import AppKit
import CryptoKit
import ServiceManagement

let fm = FileManager.default
let home = fm.homeDirectoryForCurrentUser
let payload = Bundle.main.resourceURL!.appendingPathComponent("app")
let support = home.appendingPathComponent("Library/Application Support/LLM Usage")
let venv = support.appendingPathComponent("venv")
let logURL = home.appendingPathComponent("Library/Logs/LLM Usage.log")
let legacyAgentLabel = "com.user.claude-bar"
let legacyAgent = home.appendingPathComponent("Library/LaunchAgents/\(legacyAgentLabel).plist")
// Same PATH the old LaunchAgent used, so the usage readers find the claude/codex CLIs.
let searchPath = ["/opt/homebrew/bin", "\(home.path)/.local/bin", "/usr/local/bin",
                  "/usr/bin", "/bin", "/usr/sbin", "/sbin"].joined(separator: ":")

func log(_ message: String) {
    let line = "\(Date().formatted(.iso8601)) [launcher] \(message)\n"
    if let handle = try? FileHandle(forWritingTo: logURL) {
        handle.seekToEndOfFile(); handle.write(line.data(using: .utf8)!); try? handle.close()
    } else {
        try? line.write(to: logURL, atomically: true, encoding: .utf8)
    }
}

func findUV() -> String? {
    ["\(home.path)/.local/bin/uv", "/opt/homebrew/bin/uv", "/usr/local/bin/uv"]
        .first { fm.isExecutableFile(atPath: $0) }
}

/// Run a process to completion, appending its output to the log. Returns the exit status.
@discardableResult
func run(_ exe: String, _ args: [String], env extra: [String: String] = [:]) -> Int32 {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: exe)
    p.arguments = args
    p.environment = ProcessInfo.processInfo.environment.merging(extra) { $1 }
    if let out = try? FileHandle(forWritingTo: logURL) { out.seekToEndOfFile(); p.standardOutput = out; p.standardError = out }
    do { try p.run() } catch { log("couldn't run \(exe): \(error)"); return -1 }
    p.waitUntilExit()
    return p.terminationStatus
}

/// Make the venv match uv.lock; skipped when the lock hasn't changed since the last sync.
func ensureEnvironment() -> Bool {
    let lock = payload.appendingPathComponent("uv.lock")
    guard let lockData = try? Data(contentsOf: lock) else { log("uv.lock missing from the app bundle"); return false }
    let digest = SHA256.hash(data: lockData).map { String(format: "%02x", $0) }.joined()
    let stamp = support.appendingPathComponent("venv.lock-sha256")
    let python = venv.appendingPathComponent("bin/python")
    if (try? String(contentsOf: stamp, encoding: .utf8)) == digest, fm.isExecutableFile(atPath: python.path) { return true }
    guard let uv = findUV() else { log("uv not found (install it: https://docs.astral.sh/uv/)"); return false }
    log("syncing Python environment with uv.lock")
    let status = run(uv, ["sync", "--frozen", "--no-install-project", "--project", payload.path],
                     env: ["UV_PROJECT_ENVIRONMENT": venv.path, "PATH": searchPath])
    guard status == 0 else { log("uv sync failed (\(status))"); return false }
    try? digest.write(to: stamp, atomically: true, encoding: .utf8)
    return true
}

/// Register as a login item; retire the old LaunchAgent and the copy it started.
func migrateLoginItem() {
    if fm.fileExists(atPath: legacyAgent.path) {
        run("/bin/launchctl", ["bootout", "gui/\(getuid())/\(legacyAgentLabel)"])
        try? fm.removeItem(at: legacyAgent)
        log("replaced LaunchAgent \(legacyAgentLabel) with a login item")
        try? SMAppService.mainApp.register()
    } else if UserDefaults.standard.object(forKey: "loginItemRegistered") == nil {
        try? SMAppService.mainApp.register()
    }
    UserDefaults.standard.set(true, forKey: "loginItemRegistered")
}

final class Launcher: NSObject, NSApplicationDelegate {
    var child: Process?
    var quitting = false
    var crashes: [Date] = []
    var signalSources: [DispatchSourceSignal] = []

    func applicationDidFinishLaunching(_ note: Notification) {
        try? fm.createDirectory(at: support, withIntermediateDirectories: true)
        try? fm.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        // pkill / macapp send SIGTERM: stop Python too instead of leaving it orphaned.
        for sig in [SIGTERM, SIGINT] {
            signal(sig, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
            source.setEventHandler { NSApp.terminate(nil) }
            source.resume()
            signalSources.append(source)
        }
        migrateLoginItem()
        DispatchQueue.global().async {
            let ok = ensureEnvironment()
            DispatchQueue.main.async {
                if ok { self.startChild() } else { self.failAndQuit() }
            }
        }
    }

    func startChild() {
        let p = Process()
        p.executableURL = venv.appendingPathComponent("bin/python")
        p.arguments = [payload.appendingPathComponent("claude_bar.py").path]
        p.currentDirectoryURL = payload
        p.environment = ProcessInfo.processInfo.environment.merging([
            "PATH": searchPath,
            "PYTHONDONTWRITEBYTECODE": "1",                    // the bundle is read-only
            "CLAUDE_BAR_GITHUB_REPO": "wrinkledeth/llm-usage", // update check: this fork, not upstream
        ]) { $1 }
        if let out = try? FileHandle(forWritingTo: logURL) { out.seekToEndOfFile(); p.standardOutput = out; p.standardError = out }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async { self?.childExited(proc.terminationStatus, proc.terminationReason) }
        }
        do { try p.run(); child = p; log("started (pid \(p.processIdentifier))") }
        catch { log("couldn't start Python: \(error)"); failAndQuit() }
    }

    func childExited(_ status: Int32, _ reason: Process.TerminationReason) {
        child = nil
        if quitting { return }
        if reason == .exit && status == 0 { log("Python quit; quitting"); NSApp.terminate(nil); return }
        // Crashed: restart, unless it keeps crashing (3 times within a minute).
        let now = Date()
        crashes = crashes.filter { now.timeIntervalSince($0) < 60 } + [now]
        log("Python exited (\(reason == .exit ? "status" : "signal") \(status))")
        if crashes.count >= 3 { failAndQuit(); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { self.startChild() }
    }

    func failAndQuit() {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "LLM Usage couldn't start"
        alert.informativeText = "See \(logURL.path) for details."
        alert.runModal()
        NSApp.terminate(nil)
    }

    func applicationWillTerminate(_ note: Notification) {
        quitting = true
        guard let p = child, p.isRunning else { return }
        p.terminate()
        let deadline = Date().addingTimeInterval(3)
        while p.isRunning && Date() < deadline { usleep(50_000) }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }
}

let app = NSApplication.shared
let delegate = Launcher()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
