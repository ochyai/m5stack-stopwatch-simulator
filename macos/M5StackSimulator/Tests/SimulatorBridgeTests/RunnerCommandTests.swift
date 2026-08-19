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
