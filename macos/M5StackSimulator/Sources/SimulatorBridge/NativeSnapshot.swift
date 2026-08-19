import Foundation

public struct NativeSnapshot: Sendable, Equatable {
    public static let maximumFrameBytes = 4 * 1024 * 1024

    public let root: [String: JSONValue]

    public init(root: [String: JSONValue]) {
        self.root = root
    }

    public init(lineData: Data) throws {
        guard !lineData.isEmpty else {
            throw SnapshotError.emptyFrame
        }
        guard lineData.count <= Self.maximumFrameBytes else {
            throw SnapshotError.frameTooLarge
        }

        do {
            let decoded = try JSONDecoder().decode(JSONValue.self, from: lineData)
            guard case let .object(root) = decoded else {
                throw SnapshotError.rootIsNotObject
            }
            self.root = root
        } catch let error as SnapshotError {
            throw error
        } catch {
            throw SnapshotError.invalidJSON(error.localizedDescription)
        }
    }

    public var firmwareID: String? {
        root["firmware"]?.objectValue?["id"]?.stringValue
    }

    public var commandError: String? {
        guard let message = root["command_error"]?.stringValue, !message.isEmpty else {
            return nil
        }
        return message
    }

    public var revision: UInt64? {
        guard let number = root["revision"]?.numberValue,
              number.isFinite,
              number >= 0,
              number.rounded(.towardZero) == number,
              number <= Double(UInt64.max)
        else {
            return nil
        }
        return UInt64(number)
    }

    public func encodedData() throws -> Data {
        try JSONEncoder().encode(JSONValue.object(root))
    }
}

public enum SnapshotError: Error, Sendable, Equatable, LocalizedError {
    case emptyFrame
    case frameTooLarge
    case rootIsNotObject
    case invalidJSON(String)

    public var errorDescription: String? {
        return switch self {
        case .emptyFrame:
            "native runner returned an empty frame"
        case .frameTooLarge:
            "native runner frame exceeded 4 MiB"
        case .rootIsNotObject:
            "native runner snapshot root was not an object"
        case let .invalidJSON(message):
            "native runner returned invalid JSON: \(message)"
        }
    }
}
