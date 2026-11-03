import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let store = UsageStore()
    private var statusItem: StatusItemController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        if CommandLine.arguments.contains("--print") {
            Task { await DebugPrint.run(); exit(0) }
            return
        }
        if let i = CommandLine.arguments.firstIndex(of: "--snapshot"), i + 1 < CommandLine.arguments.count {
            let dir = URL(fileURLWithPath: CommandLine.arguments[i + 1])
            Task { await DebugPrint.snapshot(store: store, to: dir); exit(0) }
            return
        }
        Log.write("started \(Bundle.main.shortVersion)")
        LaunchAtLogin.migrateOnFirstRun()

        let controller = StatusItemController(store: store)
        controller.start()
        statusItem = controller
        store.start()
    }

    func applicationWillTerminate(_ notification: Notification) {
        statusItem?.stop()
    }
}

extension Bundle {
    var shortVersion: String {
        let version = object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
        let commit = object(forInfoDictionaryKey: "HomegrownCommit") as? String
        return commit.map { "\(version) (\($0))" } ?? version
    }
}
