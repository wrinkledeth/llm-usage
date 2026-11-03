import AppKit
import LLMUsageCore
import SwiftUI

extension ProviderID {
    var accent: Color {
        switch self {
        case .codex: Color(red: 0x7B / 255, green: 0xA3 / 255, blue: 0xCD / 255)
        case .claude: Color(red: 0xC6 / 255, green: 0x88 / 255, blue: 0x70 / 255)
        case .opencode: Color(red: 0x6E / 255, green: 0x85 / 255, blue: 0xF7 / 255)
        }
    }

    /// Monochrome template logo from Contents/Resources/Icons.
    @MainActor var icon: NSImage? { ProviderIcons.image(for: self) }
}

@MainActor
private enum ProviderIcons {
    static var cache: [ProviderID: NSImage] = [:]

    static func image(for provider: ProviderID) -> NSImage? {
        if let cached = cache[provider] { return cached }
        let ext = provider == .claude ? "png" : "svg"
        guard let url = Bundle.main.url(forResource: provider.rawValue, withExtension: ext, subdirectory: "Icons"),
              let image = NSImage(contentsOf: url) else { return nil }
        image.isTemplate = true
        cache[provider] = image
        return image
    }
}

struct ProviderIconView: View {
    let provider: ProviderID

    var body: some View {
        if let icon = provider.icon {
            Image(nsImage: icon)
                .renderingMode(.template)
                .resizable()
                .interpolation(.high)
                .aspectRatio(contentMode: .fit)
        } else {
            Image(systemName: "circle.dashed").resizable().aspectRatio(contentMode: .fit)
        }
    }
}
