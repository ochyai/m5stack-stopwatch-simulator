import Foundation
import UniformTypeIdentifiers

public struct WebResource: Sendable, Equatable {
    public let fileURL: URL
    public let mimeType: String

    public init(fileURL: URL, mimeType: String) {
        self.fileURL = fileURL
        self.mimeType = mimeType
    }
}

public struct WebResourceResolver: Sendable {
    public let rootURL: URL
    private let canonicalRootPath: String

    public init(rootURL: URL) throws {
        let canonical = rootURL.resolvingSymlinksInPath().standardizedFileURL
        var isDirectory: ObjCBool = false
        guard canonical.isFileURL,
              FileManager.default.fileExists(atPath: canonical.path, isDirectory: &isDirectory),
              isDirectory.boolValue
        else {
            throw WebResourceError.missingRoot(rootURL.path)
        }
        self.rootURL = canonical
        self.canonicalRootPath = canonical.path.hasSuffix("/")
            ? canonical.path
            : canonical.path + "/"
    }

    public func resolve(path rawPath: String) throws -> WebResource {
        guard !rawPath.contains("\0"), !rawPath.contains("\\") else {
            throw WebResourceError.unsafePath
        }
        let decoded = rawPath.removingPercentEncoding ?? rawPath
        let components = decoded.split(separator: "/", omittingEmptySubsequences: true)
        guard !components.contains(where: { $0 == "." || $0 == ".." }) else {
            throw WebResourceError.unsafePath
        }

        var candidate = rootURL
        for component in components {
            candidate.appendPathComponent(String(component), isDirectory: false)
        }
        if components.isEmpty {
            candidate.appendPathComponent("index.html", isDirectory: false)
        }
        candidate = candidate.resolvingSymlinksInPath().standardizedFileURL

        guard candidate.path.hasPrefix(canonicalRootPath) else {
            throw WebResourceError.unsafePath
        }

        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: candidate.path, isDirectory: &isDirectory),
           !isDirectory.boolValue
        {
            return WebResource(fileURL: candidate, mimeType: Self.mimeType(for: candidate))
        }

        // Client-side routes resolve to index.html; missing files with an
        // extension remain hard failures so broken assets cannot be hidden.
        if candidate.pathExtension.isEmpty {
            let index = rootURL
                .appendingPathComponent("index.html")
                .resolvingSymlinksInPath()
                .standardizedFileURL
            guard index.path.hasPrefix(canonicalRootPath) else {
                throw WebResourceError.unsafePath
            }
            var indexIsDirectory: ObjCBool = false
            guard FileManager.default.fileExists(
                      atPath: index.path,
                      isDirectory: &indexIsDirectory
                  ),
                  !indexIsDirectory.boolValue
            else {
                throw WebResourceError.notFound(rawPath)
            }
            return WebResource(fileURL: index, mimeType: "text/html")
        }
        throw WebResourceError.notFound(rawPath)
    }

    private static func mimeType(for url: URL) -> String {
        if let type = UTType(filenameExtension: url.pathExtension),
           let mime = type.preferredMIMEType
        {
            return mime
        }
        return switch url.pathExtension.lowercased() {
        case "js", "mjs": "text/javascript"
        case "css": "text/css"
        case "json", "map": "application/json"
        case "svg": "image/svg+xml"
        case "wasm": "application/wasm"
        default: "application/octet-stream"
        }
    }
}

public enum WebResourceError: Error, Sendable, Equatable, LocalizedError {
    case missingRoot(String)
    case unsafePath
    case notFound(String)

    public var errorDescription: String? {
        return switch self {
        case let .missingRoot(path):
            "web asset root is missing: \(path)"
        case .unsafePath:
            "web asset path escaped the application resource root"
        case let .notFound(path):
            "web asset was not found: \(path)"
        }
    }
}
