// swift-tools-version:5.9
// Native launcher for the Python menu-bar app (see Sources/LLMUsage/main.swift).
import PackageDescription

let package = Package(
    name: "LLMUsage",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "LLMUsage", path: "Sources/LLMUsage")
    ]
)
