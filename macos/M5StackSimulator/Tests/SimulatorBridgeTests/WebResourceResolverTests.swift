import Foundation
import SimulatorBridge
import XCTest

final class WebResourceResolverTests: XCTestCase {
    func testResolvesAssetsAndClientRoutesWithinRoot() throws {
        let temporary = try TemporaryDirectory()
        try temporary.write("index.html", contents: "<main>Workbench</main>")
        let script = try temporary.write("assets/app.js", contents: "export {}")
        let resolver = try WebResourceResolver(rootURL: temporary.url)

        XCTAssertEqual(try resolver.resolve(path: "/assets/app.js").fileURL, script)
        XCTAssertEqual(try resolver.resolve(path: "/assets/app.js").mimeType, "text/javascript")
        XCTAssertEqual(try resolver.resolve(path: "/firmware/10_sokkon").fileURL.lastPathComponent, "index.html")
    }

    func testRejectsTraversalAndEscapingSymlink() throws {
        let temporary = try TemporaryDirectory()
        try temporary.write("index.html", contents: "ok")
        let outside = FileManager.default.temporaryDirectory
            .appendingPathComponent("M5StackSimulatorOutside-\(UUID().uuidString).txt")
        try "secret".write(to: outside, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: outside) }
        try FileManager.default.createSymbolicLink(
            at: temporary.url.appendingPathComponent("leak.txt"),
            withDestinationURL: outside
        )
        let resolver = try WebResourceResolver(rootURL: temporary.url)

        XCTAssertThrowsError(try resolver.resolve(path: "/%2e%2e/outside.txt")) { error in
            XCTAssertEqual(error as? WebResourceError, .unsafePath)
        }
        XCTAssertThrowsError(try resolver.resolve(path: "/leak.txt")) { error in
            XCTAssertEqual(error as? WebResourceError, .unsafePath)
        }
    }

    func testClientRouteDoesNotFollowEscapingIndexSymlink() throws {
        let temporary = try TemporaryDirectory()
        let outside = FileManager.default.temporaryDirectory
            .appendingPathComponent("M5StackSimulatorIndex-\(UUID().uuidString).html")
        try "outside".write(to: outside, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: outside) }
        try FileManager.default.createSymbolicLink(
            at: temporary.url.appendingPathComponent("index.html"),
            withDestinationURL: outside
        )
        let resolver = try WebResourceResolver(rootURL: temporary.url)

        XCTAssertThrowsError(try resolver.resolve(path: "/firmware/sokkon")) { error in
            XCTAssertEqual(error as? WebResourceError, .unsafePath)
        }
    }

    func testClientRouteFailsWhenIndexIsMissingOrDirectory() throws {
        let missing = try TemporaryDirectory()
        let missingResolver = try WebResourceResolver(rootURL: missing.url)
        XCTAssertThrowsError(try missingResolver.resolve(path: "/firmware/sokkon")) { error in
            XCTAssertEqual(error as? WebResourceError, .notFound("/firmware/sokkon"))
        }

        let directoryIndex = try TemporaryDirectory()
        try FileManager.default.createDirectory(
            at: directoryIndex.url.appendingPathComponent("index.html"),
            withIntermediateDirectories: false
        )
        let directoryResolver = try WebResourceResolver(rootURL: directoryIndex.url)
        XCTAssertThrowsError(try directoryResolver.resolve(path: "/firmware/sokkon")) { error in
            XCTAssertEqual(error as? WebResourceError, .notFound("/firmware/sokkon"))
        }
    }
}
