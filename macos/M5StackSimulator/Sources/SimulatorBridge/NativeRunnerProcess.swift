import Darwin
import Foundation

/// Owns one native firmware child process. Commands are serialized and every
/// command consumes exactly one newline-delimited JSON snapshot.
public final class NativeRunnerProcess: @unchecked Sendable {
    public static let defaultTimeout: TimeInterval = 2.0

    private let executableURL: URL
    private let maximumFrameBytes: Int
    private let writeData: (FileHandle, Data) throws -> Void
    private let requestLock = NSLock()
    private let stateLock = NSLock()
    private let lineReady = DispatchSemaphore(value: 0)
    private let processEnded = DispatchSemaphore(value: 0)

    private var process: Process?
    private var standardInput: FileHandle?
    private var standardOutput: FileHandle?
    private var standardError: FileHandle?
    private var outputBuffer = Data()
    private var responseLines: [Data] = []
    private var protocolFailure: NativeRunnerError?
    private var terminationStatus: Int32?
    private var stderrTail = Data()
    private var hasStarted = false
    private var stopped = false

    public init(executableURL: URL) {
        self.executableURL = executableURL.standardizedFileURL
        maximumFrameBytes = NativeSnapshot.maximumFrameBytes
        writeData = { handle, data in
            try handle.write(contentsOf: data)
        }
    }

    init(executableURL: URL, maximumFrameBytes: Int) {
        precondition(
            (1...NativeSnapshot.maximumFrameBytes).contains(maximumFrameBytes),
            "transport frame limit must fit the snapshot decoder limit"
        )
        self.executableURL = executableURL.standardizedFileURL
        self.maximumFrameBytes = maximumFrameBytes
        writeData = { handle, data in
            try handle.write(contentsOf: data)
        }
    }

    init(
        executableURL: URL,
        writeData: @escaping (FileHandle, Data) throws -> Void
    ) {
        self.executableURL = executableURL.standardizedFileURL
        maximumFrameBytes = NativeSnapshot.maximumFrameBytes
        self.writeData = writeData
    }

    deinit {
        stop()
    }

    public var isRunning: Bool {
        stateLock.withLock {
            process?.isRunning == true && !stopped
        }
    }

    public func start() throws {
        try stateLock.withLock {
            if process?.isRunning == true && !stopped {
                return
            }
            guard !hasStarted else {
                throw NativeRunnerError.cannotRestart
            }
            guard executableURL.isFileURL,
                  FileManager.default.isExecutableFile(atPath: executableURL.path)
            else {
                throw NativeRunnerError.executableUnavailable(executableURL.path)
            }

            let inputPipe = Pipe()
            let outputPipe = Pipe()
            let errorPipe = Pipe()
            let child = Process()
            child.executableURL = executableURL
            child.arguments = []
            child.standardInput = inputPipe
            child.standardOutput = outputPipe
            child.standardError = errorPipe

            standardInput = inputPipe.fileHandleForWriting
            standardOutput = outputPipe.fileHandleForReading
            standardError = errorPipe.fileHandleForReading
            process = child
            hasStarted = true
            stopped = false

            outputPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                self?.consumeStandardOutput(handle.availableData)
            }
            errorPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                self?.consumeStandardError(handle.availableData)
            }
            child.terminationHandler = { [weak self] child in
                self?.markTerminated(status: child.terminationStatus)
            }

            do {
                try child.run()
            } catch {
                outputPipe.fileHandleForReading.readabilityHandler = nil
                errorPipe.fileHandleForReading.readabilityHandler = nil
                process = nil
                standardInput = nil
                standardOutput = nil
                standardError = nil
                stopped = true
                throw NativeRunnerError.launchFailed(error.localizedDescription)
            }
        }
    }

    public func request(
        _ command: RunnerCommand,
        maximumAdvanceMilliseconds: UInt64 = 7 * 24 * 60 * 60 * 1_000,
        timeout: TimeInterval = NativeRunnerProcess.defaultTimeout
    ) throws -> NativeSnapshot {
        requestLock.lock()
        defer { requestLock.unlock() }

        guard timeout > 0, timeout.isFinite else {
            throw NativeRunnerError.invalidTimeout
        }
        try start()
        let wireLine = try command.wireLine(
            maximumAdvanceMilliseconds: maximumAdvanceMilliseconds
        )
        guard let data = (wireLine + "\n").data(using: .utf8) else {
            throw NativeRunnerError.commandEncodingFailed
        }

        do {
            guard let input = stateLock.withLock({ standardInput }), isRunning else {
                throw processExitError()
            }
            try writeData(input, data)
        } catch let error as NativeRunnerError {
            // A command may have been only partially delivered before the
            // transport failed. Its eventual response can no longer be paired
            // safely with another request, so this runner is permanently
            // poisoned just like a timeout or malformed frame.
            stop()
            throw error
        } catch {
            let failure = NativeRunnerError.writeFailed(error.localizedDescription)
            stop()
            throw failure
        }

        guard lineReady.wait(timeout: .now() + timeout) == .success else {
            stop()
            throw NativeRunnerError.timedOut
        }

        let result: Result<Data, NativeRunnerError> = stateLock.withLock {
            if let protocolFailure {
                self.protocolFailure = nil
                return .failure(protocolFailure)
            }
            if !responseLines.isEmpty {
                return .success(responseLines.removeFirst())
            }
            return .failure(processExitErrorLocked())
        }

        switch result {
        case let .success(line):
            do {
                return try NativeSnapshot(lineData: line)
            } catch {
                stop()
                throw NativeRunnerError.invalidSnapshot(error.localizedDescription)
            }
        case let .failure(error):
            // Any transport-level failure makes command/response alignment
            // unknowable. Never reuse that process for a later request.
            stop()
            throw error
        }
    }

    public func request(
        _ command: RunnerCommand,
        maximumAdvanceMilliseconds: UInt64 = 7 * 24 * 60 * 60 * 1_000,
        timeout: TimeInterval = NativeRunnerProcess.defaultTimeout
    ) async throws -> NativeSnapshot {
        try await Task.detached(priority: .userInitiated) { [self] in
            try request(
                command,
                maximumAdvanceMilliseconds: maximumAdvanceMilliseconds,
                timeout: timeout
            )
        }.value
    }

    /// Closes stdin first so a healthy runner exits through its normal EOF
    /// path. Signals are only used as bounded fallbacks.
    public func stop() {
        let child: Process? = stateLock.withLock {
            guard !stopped else { return nil }
            stopped = true
            let child = process
            try? standardInput?.close()
            standardInput = nil
            return child
        }
        guard let child else { return }

        if child.isRunning, processEnded.wait(timeout: .now() + 0.5) == .timedOut {
            child.terminate()
            if processEnded.wait(timeout: .now() + 0.5) == .timedOut, child.isRunning {
                kill(child.processIdentifier, SIGKILL)
                _ = processEnded.wait(timeout: .now() + 0.5)
            }
        }

        stateLock.withLock {
            standardOutput?.readabilityHandler = nil
            standardError?.readabilityHandler = nil
            try? standardOutput?.close()
            try? standardError?.close()
            standardOutput = nil
            standardError = nil
        }
    }

    private func consumeStandardOutput(_ data: Data) {
        guard !data.isEmpty else { return }
        stateLock.withLock {
            outputBuffer.append(data)
            if outputBuffer.count > maximumFrameBytes,
               !outputBuffer.contains(0x0A)
            {
                outputBuffer.removeAll(keepingCapacity: false)
                protocolFailure = .frameTooLarge
                lineReady.signal()
                return
            }

            while let newline = outputBuffer.firstIndex(of: 0x0A) {
                var line = outputBuffer.subdata(in: outputBuffer.startIndex..<newline)
                outputBuffer.removeSubrange(outputBuffer.startIndex...newline)
                if line.last == 0x0D {
                    line.removeLast()
                }
                if line.count > maximumFrameBytes {
                    protocolFailure = .frameTooLarge
                } else {
                    responseLines.append(line)
                }
                lineReady.signal()
            }
        }
    }

    private func consumeStandardError(_ data: Data) {
        guard !data.isEmpty else { return }
        stateLock.withLock {
            stderrTail.append(data)
            let maximumBytes = 64 * 1_024
            if stderrTail.count > maximumBytes {
                stderrTail.removeFirst(stderrTail.count - maximumBytes)
            }
        }
    }

    private func markTerminated(status: Int32) {
        stateLock.withLock {
            terminationStatus = status
        }
        processEnded.signal()
        lineReady.signal()
    }

    private func processExitError() -> NativeRunnerError {
        stateLock.withLock { processExitErrorLocked() }
    }

    private func processExitErrorLocked() -> NativeRunnerError {
        let stderr = String(data: stderrTail, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return .processExited(status: terminationStatus, stderr: stderr ?? "")
    }
}

public enum NativeRunnerError: Error, Sendable, Equatable, LocalizedError {
    case executableUnavailable(String)
    case launchFailed(String)
    case cannotRestart
    case invalidTimeout
    case commandEncodingFailed
    case writeFailed(String)
    case timedOut
    case frameTooLarge
    case invalidSnapshot(String)
    case processExited(status: Int32?, stderr: String)

    public var errorDescription: String? {
        switch self {
        case let .executableUnavailable(path):
            return "native runner is missing or not executable: \(path)"
        case let .launchFailed(message):
            return "native runner could not launch: \(message)"
        case .cannotRestart:
            return "a stopped native runner instance cannot be restarted"
        case .invalidTimeout:
            return "native runner timeout must be a finite positive number"
        case .commandEncodingFailed:
            return "native runner command could not be UTF-8 encoded"
        case let .writeFailed(message):
            return "native runner command write failed: \(message)"
        case .timedOut:
            return "native runner did not answer before the deadline"
        case .frameTooLarge:
            return "native runner frame exceeded 4 MiB"
        case let .invalidSnapshot(message):
            return "native runner snapshot was invalid: \(message)"
        case let .processExited(status, stderr):
            let statusText = status.map(String.init) ?? "unknown"
            return stderr.isEmpty
                ? "native runner exited (status \(statusText))"
                : "native runner exited (status \(statusText)): \(stderr)"
        }
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
