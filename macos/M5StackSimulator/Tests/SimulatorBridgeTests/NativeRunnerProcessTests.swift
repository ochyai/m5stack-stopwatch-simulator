@testable import SimulatorBridge
import XCTest

final class NativeRunnerProcessTests: XCTestCase {
    private enum InjectedWriteError: Error {
        case partialWrite
    }

    func testStartsSerializesRequestsAndStopsCleanly() throws {
        let temporary = try TemporaryDirectory()
        let executable = try temporary.write(
            "fake-runner",
            contents: fakeRunnerScript(firmwareID: "10_sokkon"),
            executable: true
        )
        let runner = NativeRunnerProcess(executableURL: executable)

        let first = try runner.request(.snapshot)
        let second = try runner.request(.action(.mode))
        XCTAssertEqual(first.firmwareID, "10_sokkon")
        XCTAssertEqual(first.revision, 1)
        XCTAssertEqual(second.revision, 2)
        XCTAssertTrue(runner.isRunning)

        runner.stop()
        XCTAssertFalse(runner.isRunning)
        XCTAssertThrowsError(try runner.start()) { error in
            XCTAssertEqual(error as? NativeRunnerError, .cannotRestart)
        }
    }

    func testTimeoutTerminatesRunnerSoLateFramesCannotDesynchronizeRequests() throws {
        let temporary = try TemporaryDirectory()
        let executable = try temporary.write(
            "silent-runner",
            contents: """
            #!/bin/sh
            IFS= read -r first
            IFS= read -r second
            """,
            executable: true
        )
        let runner = NativeRunnerProcess(executableURL: executable)

        XCTAssertThrowsError(try runner.request(.snapshot, timeout: 0.05)) { error in
            XCTAssertEqual(error as? NativeRunnerError, .timedOut)
        }
        XCTAssertFalse(runner.isRunning)
    }

    func testWriteFailurePoisonsRunnerBeforeAnotherCommandCanBeSent() throws {
        let temporary = try TemporaryDirectory()
        let executable = try temporary.write(
            "fake-runner",
            contents: fakeRunnerScript(firmwareID: "10_sokkon"),
            executable: true
        )
        let runner = NativeRunnerProcess(
            executableURL: executable,
            writeData: { input, data in
                try input.write(contentsOf: data.prefix(max(1, data.count / 2)))
                throw InjectedWriteError.partialWrite
            }
        )

        XCTAssertThrowsError(try runner.request(.snapshot)) { error in
            guard case .writeFailed = error as? NativeRunnerError else {
                return XCTFail("unexpected error: \(error)")
            }
        }
        XCTAssertFalse(runner.isRunning)
        XCTAssertThrowsError(try runner.request(.snapshot)) { error in
            XCTAssertEqual(error as? NativeRunnerError, .cannotRestart)
        }
    }

    func testMissingExecutableIsRejectedWithoutShellFallback() {
        let runner = NativeRunnerProcess(
            executableURL: URL(fileURLWithPath: "/definitely/missing/m5stack-runner")
        )
        XCTAssertThrowsError(try runner.request(.snapshot)) { error in
            guard case .executableUnavailable = error as? NativeRunnerError else {
                return XCTFail("unexpected error: \(error)")
            }
        }
    }

    func testOversizedFramePoisonsAndStopsRunner() throws {
        let temporary = try TemporaryDirectory()
        let transportFrameLimit = 64 * 1_024
        var oversizedFrame = Data(
            repeating: 0x78,
            count: transportFrameLimit + 1
        )
        oversizedFrame.append(0x0A)
        try oversizedFrame.write(
            to: temporary.url.appendingPathComponent("oversized-frame"),
            options: .atomic
        )
        let executable = try temporary.write(
            "oversized-runner",
            contents: """
            #!/bin/sh
            set -e
            IFS= read -r command
            /bin/cat "${0%/*}/oversized-frame"
            IFS= read -r next
            printf '{"revision":2,"firmware":{"id":"10_sokkon"}}\\n'
            """,
            executable: true
        )
        let runner = NativeRunnerProcess(
            executableURL: executable,
            maximumFrameBytes: transportFrameLimit
        )

        XCTAssertThrowsError(try runner.request(.snapshot, timeout: 5)) { error in
            XCTAssertEqual(error as? NativeRunnerError, .frameTooLarge)
        }
        XCTAssertFalse(runner.isRunning)
        XCTAssertThrowsError(try runner.request(.snapshot)) { error in
            XCTAssertEqual(error as? NativeRunnerError, .cannotRestart)
        }
    }

    func testPermanentLifecycleShutdownRejectsLateRunnerInstallation() throws {
        let temporary = try TemporaryDirectory()
        let executable = try temporary.write(
            "fake-runner",
            contents: fakeRunnerScript(firmwareID: "10_sokkon"),
            executable: true
        )
        let first = NativeRunnerProcess(executableURL: executable)
        try first.start()
        let lifecycle = RunnerLifecycle()
        XCTAssertTrue(lifecycle.replace(with: first))

        lifecycle.terminatePermanently()
        XCTAssertFalse(first.isRunning)
        XCTAssertNil(lifecycle.current())

        let lateRunner = NativeRunnerProcess(executableURL: executable)
        try lateRunner.start()
        XCTAssertFalse(lifecycle.replace(with: lateRunner))
        XCTAssertFalse(lateRunner.isRunning)
        XCTAssertNil(lifecycle.current())
    }
}
