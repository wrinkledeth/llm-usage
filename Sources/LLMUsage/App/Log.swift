import Foundation

/// Appends to ~/Library/Logs/LLM Usage.log (startup and provider errors only).
enum Log {
    static let url = FileManager.default.homeDirectoryForCurrentUser.appending(path: "Library/Logs/LLM Usage.log")

    static func write(_ message: String) {
        let line = "\(Date.now.formatted(.iso8601)) \(message)\n"
        if let handle = try? FileHandle(forWritingTo: url) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: Data(line.utf8))
        } else {
            try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? Data(line.utf8).write(to: url)
        }
    }
}
