import SimulatorBridge
import XCTest

final class RunnerCommandTests: XCTestCase {
    func testCommandsUseTheExistingTypedNDJSONProtocol() throws {
        XCTAssertEqual(try RunnerCommand.snapshot.wireLine(), "SNAPSHOT")
        XCTAssertEqual(try RunnerCommand.action(.mark).wireLine(), "ACTION\tMARK")
        XCTAssertEqual(try RunnerCommand.advance(milliseconds: 6_001).wireLine(), "ADVANCE\t6001")
        XCTAssertEqual(
            try RunnerCommand.configure(key: .batteryPercent, value: "84").wireLine(),
            "CONFIGURE\tBATTERY_PERCENT\t84"
        )
    }

    func testATouchCarriesItsPanelCoordinate() throws {
        XCTAssertEqual(try RunnerCommand.touch(x: 233, y: 60).wireLine(), "TOUCH\t233\t60")
        XCTAssertEqual(try RunnerCommand.touch(x: 0, y: 465).wireLine(), "TOUCH\t0\t465")
    }

    func testATouchOutsideThePanelIsRefused() {
        for point in [(x: Int32(466), y: Int32(0)), (x: Int32(0), y: Int32(466)), (x: Int32(-1), y: Int32(0))] {
            XCTAssertThrowsError(try RunnerCommand.touch(x: point.x, y: point.y).wireLine()) { error in
                XCTAssertEqual(error as? RunnerCommandError, .touchOutsidePanel)
            }
        }
    }

    func testTiltIsAnAllowlistedScenarioKey() throws {
        XCTAssertEqual(
            try RunnerCommand.configure(key: .tiltX, value: "0.6").wireLine(),
            "CONFIGURE\tTILT_X\t0.6"
        )
        XCTAssertEqual(
            try RunnerCommand.configure(key: .tiltY, value: "-0.3").wireLine(),
            "CONFIGURE\tTILT_Y\t-0.3"
        )
    }

    func testConfigurationCannotInjectAnotherCommand() {
        for value in ["hello\nACTION\tMARK", "hello\rSNAPSHOT", "hello\tSNAPSHOT", "a\0b"] {
            XCTAssertThrowsError(
                try RunnerCommand.configure(key: .context, value: value).wireLine()
            ) { error in
                XCTAssertEqual(error as? RunnerCommandError, .controlSeparator)
            }
        }
    }

    func testAdvanceAndConfigurationLengthAreBounded() {
        XCTAssertThrowsError(
            try RunnerCommand.advance(milliseconds: 600_002)
                .wireLine(maximumAdvanceMilliseconds: 600_001)
        ) { error in
            XCTAssertEqual(error as? RunnerCommandError, .advanceOutOfRange)
        }
        XCTAssertThrowsError(
            try RunnerCommand.configure(key: .detail, value: String(repeating: "a", count: 1_025))
                .wireLine()
        ) { error in
            XCTAssertEqual(error as? RunnerCommandError, .valueTooLong)
        }
    }
}
