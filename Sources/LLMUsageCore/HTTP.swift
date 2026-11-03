import Foundation

enum HTTP {
    static let userAgent = "llm-usage"

    static func send(_ request: URLRequest) async throws -> (Data, Int) {
        var request = request
        if request.value(forHTTPHeaderField: "User-Agent") == nil {
            request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        }
        if request.timeoutInterval > 30 { request.timeoutInterval = 30 }
        let (data, response) = try await URLSession.shared.data(for: request)
        return (data, (response as? HTTPURLResponse)?.statusCode ?? 0)
    }

    static func bodySnippet(_ data: Data) -> String {
        let text = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        return String(text.prefix(160))
    }
}
