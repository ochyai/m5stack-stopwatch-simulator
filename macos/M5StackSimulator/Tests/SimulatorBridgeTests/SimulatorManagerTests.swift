import SimulatorBridge
import XCTest

final class SimulatorManagerTests: XCTestCase {
    func testSwitchesOnlyBetweenAllowlistedRunnerBinaries() async throws {
        let temporary = try TemporaryDirectory()
        try temporary.write(
            FirmwareID.sokkon.executableName,
            contents: fakeRunnerScript(firmwareID: FirmwareID.sokkon.rawValue),
            executable: true
        )
        try temporary.write(
            FirmwareID.stopwatch.executableName,
            contents: fakeRunnerScript(firmwareID: FirmwareID.stopwatch.rawValue),
            executable: true
        )
        let lifecycle = RunnerLifecycle()
        let manager = SimulatorManager(
            runnerDirectory: RunnerDirectory(url: temporary.url),
            lifecycle: lifecycle
        )

        let initial = try await manager.snapshot()
        let switched = try await manager.selectFirmware(.stopwatch)
        let reset = try await manager.reset()
        XCTAssertEqual(initial.firmwareID, "10_sokkon")
        XCTAssertEqual(switched.firmwareID, "99_stopwatch")
        XCTAssertEqual(reset.firmwareID, "99_stopwatch")
        await manager.shutdown()
        XCTAssertNil(lifecycle.current())
    }

    func testRejectsMismatchedBundledRunnerIdentity() async throws {
        let temporary = try TemporaryDirectory()
        try temporary.write(
            FirmwareID.sokkon.executableName,
            contents: fakeRunnerScript(firmwareID: FirmwareID.stopwatch.rawValue),
            executable: true
        )
        let manager = SimulatorManager(runnerDirectory: RunnerDirectory(url: temporary.url))

        do {
            _ = try await manager.snapshot()
            XCTFail("expected identity mismatch")
        } catch let error as SimulatorManagerError {
            XCTAssertEqual(
                error,
                .firmwareIdentityMismatch(expected: "10_sokkon", actual: "99_stopwatch")
            )
        }
    }

    func testFailedSwitchPreservesCurrentRunnerAndSelection() async throws {
        let temporary = try TemporaryDirectory()
        try temporary.write(
            FirmwareID.sokkon.executableName,
            contents: fakeRunnerScript(firmwareID: FirmwareID.sokkon.rawValue),
            executable: true
        )
        try temporary.write(
            FirmwareID.stopwatch.executableName,
            contents: fakeRunnerScript(firmwareID: FirmwareID.sokkon.rawValue),
            executable: true
        )
        let lifecycle = RunnerLifecycle()
        let manager = SimulatorManager(
            runnerDirectory: RunnerDirectory(url: temporary.url),
            lifecycle: lifecycle
        )

        let initial = try await manager.snapshot()
        XCTAssertEqual(initial.revision, 1)
        do {
            _ = try await manager.selectFirmware(.stopwatch)
            XCTFail("expected identity mismatch")
        } catch let error as SimulatorManagerError {
            XCTAssertEqual(
                error,
                .firmwareIdentityMismatch(expected: "99_stopwatch", actual: "10_sokkon")
            )
        }

        let afterFailure = try await manager.snapshot()
        let selectedFirmware = await manager.selectedFirmware
        XCTAssertEqual(afterFailure.firmwareID, "10_sokkon")
        XCTAssertEqual(afterFailure.revision, 2)
        XCTAssertEqual(selectedFirmware, .sokkon)
        XCTAssertTrue(lifecycle.current()?.isRunning == true)
        await manager.shutdown()
    }

    func testSelectingActiveFirmwareTransactionallyBootsFreshRunner() async throws {
        let temporary = try TemporaryDirectory()
        try temporary.write(
            FirmwareID.sokkon.executableName,
            contents: fakeRunnerScript(firmwareID: FirmwareID.sokkon.rawValue),
            executable: true
        )
        let lifecycle = RunnerLifecycle()
        let manager = SimulatorManager(
            runnerDirectory: RunnerDirectory(url: temporary.url),
            lifecycle: lifecycle
        )

        let initial = try await manager.snapshot()
        let mutated = try await manager.perform(.mode)
        let originalRunner = lifecycle.current()
        let rebuilt = try await manager.selectFirmware(.sokkon)

        XCTAssertEqual(initial.revision, 1)
        XCTAssertEqual(mutated.revision, 2)
        XCTAssertEqual(rebuilt.revision, 1)
        XCTAssertFalse(originalRunner?.isRunning == true)
        XCTAssertFalse(originalRunner === lifecycle.current())
        XCTAssertEqual(rebuilt.firmwareID, "10_sokkon")
        await manager.shutdown()
    }
}
