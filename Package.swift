// swift-tools-version:6.2
import PackageDescription

let package = Package(
    name: "LLMUsage",
    platforms: [.macOS(.v26)],
    targets: [
        // Provider fetching and parsing: no AppKit, unit-tested.
        .target(name: "LLMUsageCore", path: "Sources/LLMUsageCore"),
        // Menu-bar app: status item + SwiftUI panel.
        .executableTarget(
            name: "LLMUsage",
            dependencies: ["LLMUsageCore"],
            path: "Sources/LLMUsage"
        ),
        .testTarget(
            name: "LLMUsageCoreTests",
            dependencies: ["LLMUsageCore"],
            path: "Tests/LLMUsageCoreTests"
        ),
    ]
)
