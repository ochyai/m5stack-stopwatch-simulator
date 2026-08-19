import Foundation
import SimulatorBridge
import XCTest

final class ScreenshotDownloadPolicyTests: XCTestCase {
    func testAllowsOnlyExplicitBoundedPNGDataDownload() {
        XCTAssertTrue(ScreenshotDownloadPolicy.allowsNavigation(
            url: URL(string: "data:image/png;base64,iVBORw0KGgo="),
            shouldPerformDownload: true
        ))
        XCTAssertFalse(ScreenshotDownloadPolicy.allowsNavigation(
            url: URL(string: "data:image/png;base64,iVBORw0KGgo="),
            shouldPerformDownload: false
        ))
        XCTAssertFalse(ScreenshotDownloadPolicy.allowsNavigation(
            url: URL(string: "data:text/html;base64,PGgxPk5PPC9oMT4="),
            shouldPerformDownload: true
        ))
        XCTAssertFalse(ScreenshotDownloadPolicy.allowsNavigation(
            url: URL(string: "https://example.com/image.png"),
            shouldPerformDownload: true
        ))
    }

    func testValidatesResponseAndSanitizesSuggestedFilename() {
        XCTAssertTrue(ScreenshotDownloadPolicy.allowsResponse(
            mimeType: "image/png",
            expectedContentLength: 1_000_000
        ))
        XCTAssertFalse(ScreenshotDownloadPolicy.allowsResponse(
            mimeType: "text/html",
            expectedContentLength: 100
        ))
        XCTAssertFalse(ScreenshotDownloadPolicy.allowsResponse(
            mimeType: "image/png",
            expectedContentLength: ScreenshotDownloadPolicy.maximumDecodedPNGBytes + 1
        ))
        XCTAssertEqual(
            ScreenshotDownloadPolicy.safeFilename("../../99_stopwatch simulator.html"),
            "99_stopwatch-simulator.png"
        )
        XCTAssertEqual(ScreenshotDownloadPolicy.safeFilename("..."), "M5Stack-Simulator.png")
    }
}
