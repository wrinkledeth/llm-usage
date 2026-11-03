import AppKit
import LLMUsageCore
import SwiftUI

/// `LLMUsage --print [--codex-app-server]`: fetch every provider once, print, exit.
enum DebugPrint {
    static func run() async {
        if CommandLine.arguments.contains("--codex-app-server") {
            do {
                print(describe(try await CodexUsage.loadViaAppServer()))
            } catch {
                print("codex app-server: ERROR \(error.shortMessage)")
            }
            return
        }
        for provider in ProviderID.allCases {
            do {
                print(describe(try await provider.loadUsage()))
            } catch UsageError.notConfigured(let reason) {
                print("\(provider.rawValue): hidden (\(reason))")
            } catch {
                print("\(provider.rawValue): ERROR \(error.shortMessage)")
            }
        }
    }

    /// `LLMUsage --snapshot DIR`: refresh, then render the menu-bar label and panel to PNGs (dark mode).
    @MainActor
    static func snapshot(store: UsageStore, to dir: URL) async {
        await store.refresh()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        func render(_ view: some View, _ name: String) {
            let renderer = ImageRenderer(content: view.environment(\.colorScheme, .dark))
            renderer.scale = 3
            guard let image = renderer.nsImage, let tiff = image.tiffRepresentation,
                  let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:]) else { return }
            try? png.write(to: dir.appending(path: "\(name).png"))
            print(dir.appending(path: "\(name).png").path)
        }
        let background = Color(white: 0.12)
        render(StatusLabel(store: store) { _ in }.frame(height: 24).padding(4).background(background), "label")
        render(UsagePanel(store: store) { _ in }.background(background, in: .rect(cornerRadius: 16)), "panel")
    }

    static func describe(_ s: UsageSnapshot) -> String {
        func w(_ name: String, _ w: UsageWindow?) -> String {
            guard let w else { return "" }
            return " \(name)=\(UsageFormat.percent(w.percent)) (\(UsageFormat.windowLabel(w, fallback: "?")), resets in \(UsageFormat.countdown(to: w.resetsAt) ?? "?"))"
        }
        let credits = s.credits.map { " credits=\($0.unlimited ? "unlimited" : String(describing: $0.balance))" } ?? ""
        return "\(s.provider.rawValue):" + w("session", s.session) + w("weekly", s.weekly) + w("monthly", s.monthly) + credits
    }
}
