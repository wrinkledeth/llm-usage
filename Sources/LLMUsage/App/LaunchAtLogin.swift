import Foundation
import ServiceManagement

/// LLM Usage always opens at login: it (re)registers itself as a login item on every launch.
@MainActor
enum LaunchAtLogin {
    private static let legacyAgentLabel = "com.user.claude-bar"

    static func ensureEnabled() {
        retireLegacyAgent()
        guard SMAppService.mainApp.status != .enabled else { return }
        do {
            try SMAppService.mainApp.register()
        } catch {
            Log.write("login item registration failed: \(error.localizedDescription)")
        }
    }

    /// Remove the LaunchAgent the original install.sh created, if it's still around.
    private static func retireLegacyAgent() {
        let agent = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/LaunchAgents/\(legacyAgentLabel).plist")
        guard FileManager.default.fileExists(atPath: agent.path) else { return }
        let launchctl = Process()
        launchctl.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        launchctl.arguments = ["bootout", "gui/\(getuid())/\(legacyAgentLabel)"]
        try? launchctl.run()
        launchctl.waitUntilExit()
        try? FileManager.default.removeItem(at: agent)
        Log.write("replaced LaunchAgent \(legacyAgentLabel) with a login item")
    }
}
