import Foundation
import SimulatorBridge

enum AppResourceLocator {
    static func runnerDirectory(environment: [String: String] = ProcessInfo.processInfo.environment) -> RunnerDirectory {
        if let override = environment["M5STACK_SIMULATOR_NATIVE_ROOT"], !override.isEmpty {
            return RunnerDirectory(url: URL(fileURLWithPath: override, isDirectory: true))
        }
        if let resources = Bundle.main.resourceURL {
            let bundled = resources.appendingPathComponent("Native", isDirectory: true)
            if FileManager.default.fileExists(atPath: bundled.path) {
                return RunnerDirectory(url: bundled)
            }
        }
        if let repository = repositoryRoot() {
            return RunnerDirectory(
                url: repository.appendingPathComponent(".simulator", isDirectory: true)
            )
        }
        // Keep the expected bundle path in the eventual error so a broken
        // package is diagnosable without falling back to a global executable.
        return RunnerDirectory(
            url: (Bundle.main.resourceURL ?? URL(fileURLWithPath: "/nonexistent"))
                .appendingPathComponent("Native", isDirectory: true)
        )
    }

    static func webRoot(environment: [String: String] = ProcessInfo.processInfo.environment) throws -> URL {
        if let override = environment["M5STACK_SIMULATOR_WEB_ROOT"], !override.isEmpty {
            return try verifiedWebRoot(URL(fileURLWithPath: override, isDirectory: true))
        }
        if let resources = Bundle.main.resourceURL {
            let bundled = resources.appendingPathComponent("Web", isDirectory: true)
            if let verified = try? verifiedWebRoot(bundled) {
                return verified
            }
        }
        if let repository = repositoryRoot() {
            let development = repository
                .appendingPathComponent("simulator/workbench/dist/client", isDirectory: true)
            if let verified = try? verifiedWebRoot(development) {
                return verified
            }
        }
        throw ResourceLocationError.webAssetsMissing
    }

    private static func verifiedWebRoot(_ url: URL) throws -> URL {
        let root = url.resolvingSymlinksInPath().standardizedFileURL
        let index = root.appendingPathComponent("index.html", isDirectory: false)
        guard FileManager.default.fileExists(atPath: index.path) else {
            throw ResourceLocationError.webAssetsMissing
        }
        return root
    }

    private static func repositoryRoot() -> URL? {
        let manager = FileManager.default
        var candidates = [
            URL(fileURLWithPath: manager.currentDirectoryPath, isDirectory: true),
            URL(fileURLWithPath: #filePath, isDirectory: false).deletingLastPathComponent(),
        ]
        if let executable = Bundle.main.executableURL {
            candidates.append(executable.deletingLastPathComponent())
        }

        for start in candidates {
            var current = start.standardizedFileURL
            for _ in 0..<10 {
                let marker = current.appendingPathComponent("scripts/build-simulator.sh")
                let package = current.appendingPathComponent("macos/M5StackSimulator/Package.swift")
                if manager.fileExists(atPath: marker.path), manager.fileExists(atPath: package.path) {
                    return current
                }
                let parent = current.deletingLastPathComponent()
                if parent.path == current.path { break }
                current = parent
            }
        }
        return nil
    }
}

enum ResourceLocationError: Error, LocalizedError {
    case webAssetsMissing

    var errorDescription: String? {
        return switch self {
        case .webAssetsMissing:
            "Firmware Workbench assets are missing. Build the distributable app with scripts/build-app.sh."
        }
    }
}
