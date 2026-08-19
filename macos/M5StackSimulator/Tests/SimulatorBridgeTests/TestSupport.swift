import Darwin
import Foundation

final class TemporaryDirectory {
    let url: URL

    init() throws {
        url = FileManager.default.temporaryDirectory
            .appendingPathComponent("M5StackSimulatorTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    deinit {
        try? FileManager.default.removeItem(at: url)
    }

    @discardableResult
    func write(_ name: String, contents: String, executable: Bool = false) throws -> URL {
        let file = url.appendingPathComponent(name, isDirectory: false)
        try FileManager.default.createDirectory(
            at: file.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        try contents.write(to: file, atomically: true, encoding: .utf8)
        if executable, chmod(file.path, 0o700) != 0 {
            throw POSIXError(.EPERM)
        }
        return file
    }
}

func fakeRunnerScript(firmwareID: String) -> String {
    """
    #!/bin/sh
    revision=0
    while IFS= read -r line; do
      revision=$((revision + 1))
      printf '{"revision":%s,"firmware":{"id":"\(firmwareID)"},"frame":{"width":466,"height":466,"commands":[]}}\\n' "$revision"
    done
    """
}
