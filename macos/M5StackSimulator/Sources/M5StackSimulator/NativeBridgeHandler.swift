import CoreFoundation
import Foundation
import SimulatorBridge
import WebKit

@MainActor
final class NativeBridgeHandler: NSObject, WKScriptMessageHandlerWithReply {
    static let bootstrapJavaScript = #"""
    (() => {
      const handler = window.webkit?.messageHandlers?.m5sim;
      if (!handler || window.m5stackSimulator?.available === true) return;

      const publishSnapshot = (value) => {
        if (value && typeof value === "object" && value.firmware && value.frame) {
          window.dispatchEvent(new CustomEvent("m5stack-simulator-snapshot", { detail: value }));
        }
        return value;
      };

      const call = async (method, payload = {}) => {
        const encoded = await handler.postMessage({ method, payload });
        const response = JSON.parse(encoded);
        if (!response.ok) throw new Error(response.error || "Native simulator request failed");
        return publishSnapshot(response.value);
      };

      const api = Object.freeze({
        available: true,
        bridgeVersion: 1,
        capabilities: () => call("capabilities"),
        snapshot: () => call("snapshot"),
        selectFirmware: (id) => call("selectFirmware", { id }),
        reset: () => call("reset"),
        action: (name) => call("action", { name }),
        touch: (x, y) => call("touch", { x, y }),
        advance: (milliseconds) => call("advance", { milliseconds }),
        configure: (key, value) => call("configure", { key, value }),
      });

      Object.defineProperty(window, "m5stackSimulator", {
        value: api,
        configurable: false,
        enumerable: true,
        writable: false,
      });
      document.documentElement.dataset.m5simNative = "macos";
      document.documentElement.style.setProperty("--m5sim-titlebar-safe-left", "78px");
      document.documentElement.style.setProperty("--m5sim-titlebar-height", "38px");

      const ready = () => window.dispatchEvent(new CustomEvent("m5stack-simulator-ready"));
      queueMicrotask(ready);
      document.addEventListener("DOMContentLoaded", ready, { once: true });
    })();
    """#

    private let manager: SimulatorManager

    init(manager: SimulatorManager) {
        self.manager = manager
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) async -> (Any?, String?) {
        let request: BridgeRequest
        do {
            request = try BridgeRequest(messageBody: message.body)
        } catch {
            return (Self.failureJSON(error), nil)
        }

        do {
            let value = try await Self.execute(request, manager: manager)
            return (Self.successJSON(value), nil)
        } catch {
            return (Self.failureJSON(error), nil)
        }
    }

    private static func execute(
        _ request: BridgeRequest,
        manager: SimulatorManager
    ) async throws -> JSONValue {
        switch request {
        case .capabilities:
            return .object([
                "bridgeVersion": .number(1),
                "firmware": .array(FirmwareID.allCases.map { firmware in
                    .object([
                        "id": .string(firmware.rawValue),
                        "label": .string(firmware.displayName),
                    ])
                }),
            ])
        case .snapshot:
            return .object(try await manager.snapshot().root)
        case let .selectFirmware(firmware):
            return .object(try await manager.selectFirmware(firmware).root)
        case .reset:
            return .object(try await manager.reset().root)
        case let .action(action):
            return .object(try await manager.perform(action).root)
        case let .touch(x, y):
            return .object(try await manager.touch(x: x, y: y).root)
        case let .advance(milliseconds):
            return .object(try await manager.advance(milliseconds: milliseconds).root)
        case let .configure(key, value):
            return .object(try await manager.configure(key: key, value: value).root)
        }
    }

    private static func successJSON(_ value: JSONValue) -> String {
        encodeEnvelope(.object(["ok": .bool(true), "value": value]))
    }

    private static func failureJSON(_ error: Error) -> String {
        encodeEnvelope(.object([
            "ok": .bool(false),
            "error": .string(error.localizedDescription),
        ]))
    }

    private static func encodeEnvelope(_ value: JSONValue) -> String {
        guard let data = try? JSONEncoder().encode(value),
              let string = String(data: data, encoding: .utf8)
        else {
            return #"{"ok":false,"error":"Native bridge encoding failed"}"#
        }
        return string
    }
}

private enum BridgeRequest: Sendable {
    case capabilities
    case snapshot
    case selectFirmware(FirmwareID)
    case reset
    case action(FirmwareAction)
    case touch(Int32, Int32)
    case advance(UInt64)
    case configure(ScenarioKey, String)

    init(messageBody: Any) throws {
        guard let message = messageBody as? [String: Any],
              let method = message["method"] as? String,
              let payload = message["payload"] as? [String: Any]
        else {
            throw NativeBridgeInputError.malformedRequest
        }

        switch method {
        case "capabilities":
            self = .capabilities
        case "snapshot":
            self = .snapshot
        case "selectFirmware":
            guard let id = payload["id"] as? String,
                  let firmware = FirmwareID(rawValue: id)
            else {
                throw NativeBridgeInputError.unsupportedFirmware
            }
            self = .selectFirmware(firmware)
        case "reset":
            self = .reset
        case "action":
            guard let name = payload["name"] as? String,
                  let action = FirmwareAction(rawValue: name.uppercased())
            else {
                throw NativeBridgeInputError.unsupportedAction
            }
            self = .action(action)
        case "touch":
            // The firmware reads where the press landed, so the coordinate is
            // validated against the panel before it reaches the runner.
            let x = try Self.unsignedInteger(payload["x"], field: "x", maximum: UInt64(displaySize - 1))
            let y = try Self.unsignedInteger(payload["y"], field: "y", maximum: UInt64(displaySize - 1))
            self = .touch(Int32(x), Int32(y))
        case "advance":
            self = .advance(try Self.unsignedInteger(
                payload["milliseconds"],
                field: "milliseconds",
                maximum: 7 * 24 * 60 * 60 * 1_000
            ))
        case "configure":
            guard let rawKey = payload["key"] as? String,
                  let key = Self.scenarioKey(rawKey)
            else {
                throw NativeBridgeInputError.unsupportedConfiguration
            }
            self = .configure(key, try Self.configurationValue(payload["value"], for: key))
        default:
            throw NativeBridgeInputError.unsupportedMethod
        }
    }

    private static func scenarioKey(_ raw: String) -> ScenarioKey? {
        switch raw {
        case "connected": .connected
        case "outcome": .outcome
        case "latency_ms": .latencyMilliseconds
        case "context": .context
        case "detail": .detail
        case "host_mode": .hostMode
        case "battery_percent": .batteryPercent
        case "charging": .charging
        case "time_scale": .timeScale
        case "tilt_x": .tiltX
        case "tilt_y": .tiltY
        default: nil
        }
    }

    private static func configurationValue(_ value: Any?, for key: ScenarioKey) throws -> String {
        switch key {
        case .connected, .charging:
            guard let value, isBoolean(value), let boolean = value as? Bool else {
                throw NativeBridgeInputError.invalidValue(key.rawValue)
            }
            return boolean ? "1" : "0"
        case .outcome:
            guard let outcome = (value as? String)?.uppercased(),
                  ["OK", "ERROR", "TIMEOUT"].contains(outcome)
            else {
                throw NativeBridgeInputError.invalidValue(key.rawValue)
            }
            return outcome
        case .latencyMilliseconds:
            return String(try unsignedInteger(value, field: key.rawValue, maximum: 60_000))
        case .context, .detail:
            guard let string = value as? String else {
                throw NativeBridgeInputError.invalidValue(key.rawValue)
            }
            let maximum = key == .context ? 256 : 512
            guard string.utf8.count <= maximum else {
                throw NativeBridgeInputError.invalidValue(key.rawValue)
            }
            return string
        case .hostMode:
            guard let mode = (value as? String)?.uppercased(),
                  ["NOW", "BUILD", "READ", "MEET", "PRESENT", "REST"].contains(mode)
            else {
                throw NativeBridgeInputError.invalidValue(key.rawValue)
            }
            return mode
        case .batteryPercent:
            return String(try unsignedInteger(value, field: key.rawValue, maximum: 100))
        case .timeScale, .tiltX, .tiltY:
            let range: ClosedRange<Double> = key == .timeScale ? 0.01...1_000 : -1...1
            guard let number = value as? NSNumber,
                  !isBoolean(number),
                  number.doubleValue.isFinite,
                  range.contains(number.doubleValue)
            else {
                throw NativeBridgeInputError.invalidValue(key.rawValue)
            }
            return String(
                format: "%.15g",
                locale: Locale(identifier: "en_US_POSIX"),
                number.doubleValue
            )
        }
    }

    private static func unsignedInteger(
        _ value: Any?,
        field: String,
        maximum: UInt64
    ) throws -> UInt64 {
        guard let number = value as? NSNumber,
              !isBoolean(number),
              number.doubleValue.isFinite,
              number.doubleValue >= 0,
              number.doubleValue.rounded(.towardZero) == number.doubleValue,
              number.doubleValue <= Double(maximum)
        else {
            throw NativeBridgeInputError.invalidValue(field)
        }
        return number.uint64Value
    }

    private static func isBoolean(_ value: Any) -> Bool {
        guard let object = value as CFTypeRef? else { return false }
        return CFGetTypeID(object) == CFBooleanGetTypeID()
    }
}

private enum NativeBridgeInputError: Error, LocalizedError {
    case malformedRequest
    case unsupportedMethod
    case unsupportedFirmware
    case unsupportedAction
    case unsupportedConfiguration
    case invalidValue(String)

    var errorDescription: String? {
        return switch self {
        case .malformedRequest:
            "native bridge request must contain a method and payload object"
        case .unsupportedMethod:
            "native bridge method is not allowlisted"
        case .unsupportedFirmware:
            "firmware must be 10_sokkon or 99_stopwatch"
        case .unsupportedAction:
            "action must be mark, mode, focus, or wake"
        case .unsupportedConfiguration:
            "configuration key is not allowlisted"
        case let .invalidValue(field):
            "configuration value is invalid for \(field)"
        }
    }
}
