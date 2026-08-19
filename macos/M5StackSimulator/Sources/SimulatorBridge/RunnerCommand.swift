import Foundation

public enum FirmwareID: String, CaseIterable, Sendable, Codable {
    case sokkon = "10_sokkon"
    case stopwatch = "99_stopwatch"

    public var displayName: String {
        return switch self {
        case .sokkon: "SOKKON"
        case .stopwatch: "STOPWATCH"
        }
    }

    public var executableName: String {
        return switch self {
        case .sokkon: "sokkon-native"
        case .stopwatch: "stopwatch-native"
        }
    }

    public var maximumAdvanceMilliseconds: UInt64 {
        return switch self {
        case .sokkon: 7 * 24 * 60 * 60 * 1_000
        case .stopwatch: 600_001
        }
    }
}

public enum FirmwareAction: String, CaseIterable, Sendable, Codable {
    case mark = "MARK"
    case mode = "MODE"
    case focus = "FOCUS"
    case wake = "WAKE"
}

public enum ScenarioKey: String, CaseIterable, Sendable, Codable {
    case connected = "CONNECTED"
    case outcome = "OUTCOME"
    case latencyMilliseconds = "LATENCY_MS"
    case context = "CONTEXT"
    case detail = "DETAIL"
    case hostMode = "HOST_MODE"
    case batteryPercent = "BATTERY_PERCENT"
    case charging = "CHARGING"
    case timeScale = "TIME_SCALE"
}

public enum RunnerCommand: Sendable, Equatable {
    case snapshot
    case action(FirmwareAction)
    case advance(milliseconds: UInt64)
    case configure(key: ScenarioKey, value: String)

    public func wireLine(maximumAdvanceMilliseconds: UInt64 = 7 * 24 * 60 * 60 * 1_000) throws -> String {
        switch self {
        case .snapshot:
            return "SNAPSHOT"
        case let .action(action):
            return "ACTION\t\(action.rawValue)"
        case let .advance(milliseconds):
            guard milliseconds <= maximumAdvanceMilliseconds else {
                throw RunnerCommandError.advanceOutOfRange
            }
            return "ADVANCE\t\(milliseconds)"
        case let .configure(key, value):
            guard value.utf8.count <= 1_024 else {
                throw RunnerCommandError.valueTooLong
            }
            guard !value.unicodeScalars.contains(where: {
                $0.value == 0 || $0.value == 9 || $0.value == 10 || $0.value == 13
            }) else {
                throw RunnerCommandError.controlSeparator
            }
            return "CONFIGURE\t\(key.rawValue)\t\(value)"
        }
    }
}

public enum RunnerCommandError: Error, Sendable, Equatable, LocalizedError {
    case advanceOutOfRange
    case valueTooLong
    case controlSeparator

    public var errorDescription: String? {
        return switch self {
        case .advanceOutOfRange:
            "virtual-time advance is outside the firmware limit"
        case .valueTooLong:
            "configuration value exceeds 1024 UTF-8 bytes"
        case .controlSeparator:
            "configuration value contains an NDJSON command separator"
        }
    }
}
