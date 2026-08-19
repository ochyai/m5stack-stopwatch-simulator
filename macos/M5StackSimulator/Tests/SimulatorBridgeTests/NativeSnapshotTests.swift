import Foundation
import SimulatorBridge
import XCTest

final class NativeSnapshotTests: XCTestCase {
    func testDecodesFirmwareIdentityAndRevisionWithoutMirroringState() throws {
        let data = Data(#"{"revision":42,"firmware":{"id":"99_stopwatch"},"frame":{"commands":[]}}"#.utf8)
        let snapshot = try NativeSnapshot(lineData: data)

        XCTAssertEqual(snapshot.firmwareID, "99_stopwatch")
        XCTAssertEqual(snapshot.revision, 42)
        XCTAssertNil(snapshot.commandError)
        XCTAssertNoThrow(try JSONSerialization.jsonObject(with: snapshot.encodedData()))
    }

    func testExposesRunnerCommandError() throws {
        let data = Data(#"{"revision":1,"firmware":{"id":"10_sokkon"},"command_error":"unsupported"}"#.utf8)
        XCTAssertEqual(try NativeSnapshot(lineData: data).commandError, "unsupported")
    }

    func testRejectsEmptyNonObjectAndOversizedFrames() {
        XCTAssertThrowsError(try NativeSnapshot(lineData: Data())) { error in
            XCTAssertEqual(error as? SnapshotError, .emptyFrame)
        }
        XCTAssertThrowsError(try NativeSnapshot(lineData: Data("[]".utf8))) { error in
            XCTAssertEqual(error as? SnapshotError, .rootIsNotObject)
        }
        XCTAssertThrowsError(
            try NativeSnapshot(lineData: Data(repeating: 0x20, count: NativeSnapshot.maximumFrameBytes + 1))
        ) { error in
            XCTAssertEqual(error as? SnapshotError, .frameTooLarge)
        }
    }
}
