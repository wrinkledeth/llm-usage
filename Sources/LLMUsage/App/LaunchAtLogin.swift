import Foundation
import ServiceManagement

/// Login item via `SMAppService.mainApp`, which is the source of truth for the toggle.
@MainActor
enum LaunchAtLogin {
    private static let legacyAgentLabel = "com.user.claude-bar"
    private static let registeredKey = "loginItemRegistered"

    static var isEnabled: Bool { SMAppService.mainApp.status == .enabled }

    static func set(_ enabled: Bool) {
        do {
            if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch {
            Log.write("login item \(enabled ? "register" : "unregister") failed: \(error.localizedDescription)")
        }
    }

    /// Opt in once on first launch, and retire the LaunchAgent the original install.sh created.
    static func migrateOnFirstRun() {
        let agent = FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/LaunchAgents/\(legacyAgentLabel).plist")
        if FileManager.default.fileExists(atPath: agent.path) {
            let launchctl = Process()
            launchctl.executableURL = URL(fileURLWithPath: "/bin/launchctl")
            launchctl.arguments = ["bootout", "gui/\(getuid())/\(legacyAgentLabel)"]
            try? launchctl.run()
            launchctl.waitUntilExit()
            try? FileManager.default.removeItem(at: agent)
            Log.write("replaced LaunchAgent \(legacyAgentLabel) with a login item")
            set(true)
        } else if UserDefaults.standard.object(forKey: registeredKey) == nil {
            set(true)
        }
        UserDefaults.standard.set(true, forKey: registeredKey)
    }
}
