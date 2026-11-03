import Foundation

/// Minimal JSON-RPC client for `codex app-server` (newline-delimited JSON over stdio).
final class CodexAppServer: @unchecked Sendable {
    static let arguments = ["-s", "read-only", "-a", "never", "app-server"]

    private let process = Process()
    private let input = Pipe()
    private let output = Pipe()
    private var lines: AsyncStream<Data>.Iterator
    private var nextID = 1

    /// Start the server, read `account/rateLimits/read`, stop it. Gives up after `timeout` seconds.
    static func readRateLimits(executable: String, env: [String: String], timeout: TimeInterval = 15) async throws -> JSONValue {
        let server = try CodexAppServer(executable: executable, env: env)
        defer { server.stop() }
        let watchdog = Task.detached { [server] in
            try? await Task.sleep(for: .seconds(timeout))
            if !Task.isCancelled { server.stop() }
        }
        defer { watchdog.cancel() }

        _ = try await server.request("initialize", params: ["clientInfo": ["name": "llm-usage", "version": "2.0.0"]])
        try server.notify("initialized")
        _ = try await server.request("account/read", params: [:])
        return try await server.request("account/rateLimits/read")
    }

    private init(executable: String, env: [String: String]) throws {
        let (stream, continuation) = AsyncStream<Data>.makeStream()
        lines = stream.makeAsyncIterator()

        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = Self.arguments
        process.environment = env
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice

        nonisolated(unsafe) var buffer = Data()
        output.fileHandleForReading.readabilityHandler = { handle in
            let chunk = handle.availableData
            if chunk.isEmpty {
                handle.readabilityHandler = nil
                continuation.finish()
                return
            }
            buffer.append(chunk)
            while let newline = buffer.firstIndex(of: 0x0A) {
                continuation.yield(buffer[buffer.startIndex..<newline])
                buffer.removeSubrange(buffer.startIndex...newline)
            }
        }
        do {
            try process.run()
        } catch {
            throw UsageError.failed("Couldn't start codex app-server: \(error.localizedDescription)")
        }
    }

    func stop() {
        if process.isRunning { process.terminate() }
        try? input.fileHandleForWriting.close()
    }

    func notify(_ method: String, params: [String: Any]? = nil) throws {
        var message: [String: Any] = ["method": method]
        if let params { message["params"] = params }
        try send(message)
    }

    func request(_ method: String, params: [String: Any]? = nil) async throws -> JSONValue {
        let id = nextID
        nextID += 1
        var message: [String: Any] = ["id": id, "method": method]
        if let params { message["params"] = params }
        try send(message)

        while let line = await lines.next() {
            guard let reply = try? JSONValue.parse(line), reply["id"]?.int == id else { continue }
            if let error = reply["error"] {
                throw UsageError.failed("codex app-server: \(error["message"]?.string ?? "error")")
            }
            guard let result = reply["result"], result.object != nil else {
                throw UsageError.failed("codex app-server returned malformed JSON-RPC")
            }
            return result
        }
        throw UsageError.failed("codex app-server exited or timed out")
    }

    private func send(_ message: [String: Any]) throws {
        var data = try JSONSerialization.data(withJSONObject: message)
        data.append(0x0A)
        try input.fileHandleForWriting.write(contentsOf: data)
    }
}
