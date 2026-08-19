import Foundation

public struct RunnerDirectory: Sendable, Equatable {
    public let url: URL

    public init(url: URL) {
        self.url = url.resolvingSymlinksInPath().standardizedFileURL
    }

    public func executableURL(for firmware: FirmwareID) -> URL {
        url.appendingPathComponent(firmware.executableName, isDirectory: false)
    }
}

public actor SimulatorManager {
    public let lifecycle: RunnerLifecycle
    public let runnerDirectory: RunnerDirectory
    public private(set) var selectedFirmware: FirmwareID

    public init(
        runnerDirectory: RunnerDirectory,
        selectedFirmware: FirmwareID = .sokkon,
        lifecycle: RunnerLifecycle = RunnerLifecycle()
    ) {
        self.runnerDirectory = runnerDirectory
        self.selectedFirmware = selectedFirmware
        self.lifecycle = lifecycle
    }

    public func snapshot() async throws -> NativeSnapshot {
        let runner = try ensureRunner()
        do {
            return try checkedRequest(.snapshot, using: runner, firmware: selectedFirmware)
        } catch let error as SimulatorManagerError {
            if case .firmwareIdentityMismatch = error {
                lifecycle.shutdown()
            }
            throw error
        }
    }

    public func selectFirmware(_ firmware: FirmwareID) async throws -> NativeSnapshot {
        // Switching is transactional: compile/package selection can never
        // strand the UI without its previously healthy runner. The candidate
        // must launch, answer, and prove its embedded firmware identity before
        // RunnerLifecycle atomically installs it and stops the old process.
        // This also applies to the already-selected ID: Workbench's Build &
        // Run button must boot a fresh copy of the bundled production binary,
        // not falsely report success after returning an old snapshot.
        let candidate = NativeRunnerProcess(
            executableURL: runnerDirectory.executableURL(for: firmware)
        )
        do {
            try candidate.start()
            let candidateSnapshot = try checkedRequest(
                .snapshot,
                using: candidate,
                firmware: firmware
            )
            guard lifecycle.replace(with: candidate) else {
                throw SimulatorManagerError.lifecycleTerminated
            }
            selectedFirmware = firmware
            return candidateSnapshot
        } catch {
            candidate.stop()
            throw error
        }
    }

    public func reset() async throws -> NativeSnapshot {
        let candidate = NativeRunnerProcess(
            executableURL: runnerDirectory.executableURL(for: selectedFirmware)
        )
        do {
            try candidate.start()
            let candidateSnapshot = try checkedRequest(
                .snapshot,
                using: candidate,
                firmware: selectedFirmware
            )
            guard lifecycle.replace(with: candidate) else {
                throw SimulatorManagerError.lifecycleTerminated
            }
            return candidateSnapshot
        } catch {
            candidate.stop()
            throw error
        }
    }

    public func perform(_ action: FirmwareAction) async throws -> NativeSnapshot {
        let runner = try ensureRunner()
        return try checkedRequest(.action(action), using: runner, firmware: selectedFirmware)
    }

    public func advance(milliseconds: UInt64) async throws -> NativeSnapshot {
        guard milliseconds <= selectedFirmware.maximumAdvanceMilliseconds else {
            throw SimulatorManagerError.advanceOutOfRange(
                maximum: selectedFirmware.maximumAdvanceMilliseconds
            )
        }
        let runner = try ensureRunner()
        return try checkedRequest(
            .advance(milliseconds: milliseconds),
            using: runner,
            firmware: selectedFirmware
        )
    }

    public func configure(key: ScenarioKey, value: String) async throws -> NativeSnapshot {
        let runner = try ensureRunner()
        return try checkedRequest(
            .configure(key: key, value: value),
            using: runner,
            firmware: selectedFirmware
        )
    }

    public func shutdown() {
        lifecycle.shutdown()
    }

    private func ensureRunner() throws -> NativeRunnerProcess {
        if let runner = lifecycle.current(), runner.isRunning {
            return runner
        }

        lifecycle.shutdown()
        let runner = NativeRunnerProcess(
            executableURL: runnerDirectory.executableURL(for: selectedFirmware)
        )
        do {
            try runner.start()
        } catch {
            runner.stop()
            throw error
        }
        guard lifecycle.replace(with: runner) else {
            throw SimulatorManagerError.lifecycleTerminated
        }
        return runner
    }

    private func checkedRequest(
        _ command: RunnerCommand,
        using runner: NativeRunnerProcess,
        firmware: FirmwareID
    ) throws -> NativeSnapshot {
        let snapshot = try runner.request(
            command,
            maximumAdvanceMilliseconds: firmware.maximumAdvanceMilliseconds
        )
        guard snapshot.firmwareID == firmware.rawValue else {
            throw SimulatorManagerError.firmwareIdentityMismatch(
                expected: firmware.rawValue,
                actual: snapshot.firmwareID
            )
        }
        if let message = snapshot.commandError {
            throw SimulatorManagerError.runnerRejected(message)
        }
        return snapshot
    }
}

public enum SimulatorManagerError: Error, Sendable, Equatable, LocalizedError {
    case firmwareIdentityMismatch(expected: String, actual: String?)
    case runnerRejected(String)
    case advanceOutOfRange(maximum: UInt64)
    case lifecycleTerminated

    public var errorDescription: String? {
        return switch self {
        case let .firmwareIdentityMismatch(expected, actual):
            "native runner identity mismatch; expected \(expected), got \(actual ?? "missing")"
        case let .runnerRejected(message):
            "native runner rejected the command: \(message)"
        case let .advanceOutOfRange(maximum):
            "virtual-time advance exceeds this firmware's \(maximum) ms limit"
        case .lifecycleTerminated:
            "the simulator application is terminating"
        }
    }
}
