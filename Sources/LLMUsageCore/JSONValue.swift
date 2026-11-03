import Foundation

/// Loosely-typed JSON for provider responses whose shapes vary between versions.
public enum JSONValue: Sendable, Equatable, Decodable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    public static func parse(_ data: Data) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: data)
    }

    public static func parse(_ text: String) throws -> JSONValue {
        try parse(Data(text.utf8))
    }

    public subscript(key: String) -> JSONValue? {
        if case .object(let o) = self { return o[key] }
        return nil
    }

    public var object: [String: JSONValue]? {
        if case .object(let o) = self { return o }
        return nil
    }

    /// Numbers, or strings holding numbers (APIs send both).
    public var double: Double? {
        switch self {
        case .number(let d): d
        case .string(let s): Double(s.trimmingCharacters(in: .whitespaces))
        default: nil
        }
    }

    public var int: Int? { double.map { Int($0) } }

    public var string: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    /// Non-empty trimmed string.
    public var nonEmptyString: String? {
        guard let s = string?.trimmingCharacters(in: .whitespacesAndNewlines), !s.isEmpty else { return nil }
        return s
    }

    /// JSON truthiness (true, non-zero numbers).
    public var isTruthy: Bool {
        switch self {
        case .bool(let b): b
        case .number(let d): d != 0
        case .string(let s): !s.isEmpty
        case .array(let a): !a.isEmpty
        case .object(let o): !o.isEmpty
        case .null: false
        }
    }
}

enum ISODate {
    /// Parses RFC 3339 timestamps with any number of fractional digits and Z or ±hh:mm offsets.
    static func parse(_ raw: String?) -> Date? {
        guard var text = raw?.trimmingCharacters(in: .whitespaces), !text.isEmpty else { return nil }
        if let range = text.range(of: #"\.\d+"#, options: .regularExpression) {
            text.removeSubrange(range)
        }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: text)
    }

    static func format(_ date: Date) -> String {
        date.formatted(Date.ISO8601FormatStyle(includingFractionalSeconds: true))
    }
}
