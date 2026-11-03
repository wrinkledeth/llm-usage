import AppKit
import SwiftUI

/// Owns the menu-bar item: draws `StatusLabel` in the button, shows `UsagePanel` on left click
/// and a small menu on right click.
@MainActor
final class StatusItemController: NSObject {
    private let store: UsageStore
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private var label: PassthroughHostingView<StatusLabel>?
    private var panel: NSPanel?
    private var panelHost: NSHostingView<UsagePanel>?
    private var panelSize = NSSize(width: 310, height: 300)
    private var globalMonitor: Any?
    private var localMonitor: Any?
    private let menu = NSMenu()

    init(store: UsageStore) {
        self.store = store
        super.init()
        buildMenu()
    }

    func start() {
        guard let button = item.button else { return }
        button.target = self
        button.action = #selector(buttonClicked(_:))
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])

        let host = PassthroughHostingView(rootView: StatusLabel(store: store) { [weak self] size in
            self?.layoutLabel(size)
        })
        button.addSubview(host)
        label = host
        layoutLabel(host.fittingSize)
    }

    func stop() {
        removeMonitors()
        panel?.orderOut(nil)
        NSStatusBar.system.removeStatusItem(item)
    }

    private func layoutLabel(_ size: CGSize) {
        guard let button = item.button, let label else { return }
        let width = ceil(max(size.width, 16))
        item.length = width
        let height = button.bounds.height > 0 ? button.bounds.height : NSStatusBar.system.thickness
        label.frame = NSRect(x: 0, y: (height - size.height) / 2, width: width, height: size.height)
    }

    // MARK: Clicks and menu

    private func buildMenu() {
        let refresh = NSMenuItem(title: "Refresh", action: #selector(refreshNow), keyEquivalent: "r")
        refresh.target = self
        menu.addItem(refresh)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit LLM Usage", action: #selector(quit), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
    }

    @objc private func buttonClicked(_ sender: NSStatusBarButton) {
        if NSApp.currentEvent?.type == .rightMouseUp {
            hidePanel()
            menu.popUp(positioning: nil, at: NSPoint(x: 0, y: sender.bounds.height + 4), in: sender)
        } else if panel?.isVisible == true {
            hidePanel()
        } else {
            showPanel()
        }
    }

    @objc private func refreshNow() { Task { await store.refresh() } }
    @objc private func quit() { NSApp.terminate(nil) }

    // MARK: Panel

    private func showPanel() {
        let panel = self.panel ?? makePanel()
        self.panel = panel
        if panelHost == nil {
            let host = NSHostingView(rootView: UsagePanel(store: store) { [weak self] size in
                self?.resizePanel(to: size)
            })
            host.autoresizingMask = [.width, .height]
            if let glass = panel.contentView as? NSGlassEffectView {
                glass.contentView = host
            } else {
                panel.contentView?.addSubview(host)
            }
            panelHost = host
            panelSize = host.fittingSize
        }
        store.refreshIfStale()
        positionPanel()
        panel.makeKeyAndOrderFront(nil)
        // Install after this click has been handled so it doesn't close the panel immediately.
        DispatchQueue.main.async { [weak self] in self?.installMonitors() }
    }

    private func hidePanel() {
        panel?.orderOut(nil)
        removeMonitors()
    }

    private func resizePanel(to size: CGSize) {
        guard size.height > 0, size != panelSize else { return }
        panelSize = size
        if panel?.isVisible == true { positionPanel() }
    }

    /// Centered under the menu-bar item, top edge pinned to the menu bar, kept on screen.
    private func positionPanel() {
        guard let panel, let button = item.button, let window = button.window,
              let screen = window.screen ?? NSScreen.main else { return }
        let anchor = window.convertToScreen(button.convert(button.bounds, to: nil))
        let visible = screen.visibleFrame
        let x = min(max(anchor.midX - panelSize.width / 2, visible.minX + 4), visible.maxX - panelSize.width - 4)
        let top = visible.maxY - 0.5
        panel.setFrame(NSRect(x: x, y: top - panelSize.height, width: panelSize.width, height: panelSize.height),
                       display: true)
    }

    private func makePanel() -> NSPanel {
        let panel = NSPanel(
            contentRect: NSRect(origin: .zero, size: panelSize),
            styleMask: [.titled, .nonactivatingPanel, .utilityWindow, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isFloatingPanel = true
        panel.level = .statusBar
        panel.becomesKeyOnlyIfNeeded = true
        panel.hasShadow = true
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovable = false
        for button in [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton] {
            panel.standardWindowButton(button)?.isHidden = true
        }
        let glass = NSGlassEffectView(frame: NSRect(origin: .zero, size: panelSize))
        glass.style = .regular
        glass.cornerRadius = 16
        glass.autoresizingMask = [.width, .height]
        panel.contentView = glass
        return panel
    }

    private func installMonitors() {
        guard globalMonitor == nil else { return }
        globalMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            MainActor.assumeIsolated { self?.hidePanel() }
        }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown]) { [weak self] event in
            guard event.keyCode == 53 else { return event }  // Esc
            MainActor.assumeIsolated { self?.hidePanel() }
            return nil
        }
    }

    private func removeMonitors() {
        if let globalMonitor { NSEvent.removeMonitor(globalMonitor) }
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
        globalMonitor = nil
        localMonitor = nil
    }
}

/// Lets clicks fall through to the status-bar button underneath.
final class PassthroughHostingView<Content: View>: NSHostingView<Content> {
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}
