import Foundation
import SimulatorBridge
import WebKit

final class WebSchemeHandler: NSObject, WKURLSchemeHandler, @unchecked Sendable {
    private let resourceLoader: WebResourceLoader
    private let taskRegistry = SchemeTaskRegistry()
    private let inputOutputQueue = DispatchQueue(
        label: "com.ochyai.m5stack-simulator.web-resources",
        qos: .userInitiated
    )

    init(webRoot: URL) {
        self.resourceLoader = WebResourceLoader(webRoot: webRoot)
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: any WKURLSchemeTask) {
        let task = SchemeTaskBox(urlSchemeTask)
        let identifier = ObjectIdentifier(task.task)
        taskRegistry.begin(identifier)
        let registry = taskRegistry
        let loader = resourceLoader

        inputOutputQueue.async { [task] in
            guard registry.isActive(identifier) else {
                registry.finish(identifier)
                return
            }
            let result = loader.load(request: task.task.request)

            DispatchQueue.main.async { [task] in
                defer { registry.finish(identifier) }
                switch result {
                case let .success(response, data):
                    guard registry.deliver(identifier, { task.task.didReceive(response) }) else { return }
                    guard registry.deliver(identifier, { task.task.didReceive(data) }) else { return }
                    _ = registry.deliver(identifier, { task.task.didFinish() })
                case let .failure(error):
                    _ = registry.deliver(identifier, { task.task.didFailWithError(error) })
                }
            }
        }
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: any WKURLSchemeTask) {
        taskRegistry.cancel(ObjectIdentifier(urlSchemeTask))
    }
}

private final class WebResourceLoader: @unchecked Sendable {
    private let resolver: Result<WebResourceResolver, Error>

    init(webRoot: URL) {
        self.resolver = Result { try WebResourceResolver(rootURL: webRoot) }
    }

    func load(request: URLRequest) -> SchemeLoadResult {
        do {
            guard let url = request.url, url.host == "app" else {
                throw URLError(.badURL)
            }
            let resolver = try resolver.get()
            let resource = try resolver.resolve(path: url.path)
            let data = try Data(contentsOf: resource.fileURL, options: .mappedIfSafe)
            let response = URLResponse(
                url: url,
                mimeType: resource.mimeType,
                expectedContentLength: data.count,
                textEncodingName: resource.mimeType.hasPrefix("text/") ? "utf-8" : nil
            )
            return .success(response, data)
        } catch {
            return .failure(error)
        }
    }
}

private final class SchemeTaskRegistry: @unchecked Sendable {
    private let lock = NSRecursiveLock()
    private var active: Set<ObjectIdentifier> = []

    func begin(_ identifier: ObjectIdentifier) {
        lock.withLock { _ = active.insert(identifier) }
    }

    func cancel(_ identifier: ObjectIdentifier) {
        lock.withLock {
            _ = active.remove(identifier)
        }
    }

    func isActive(_ identifier: ObjectIdentifier) -> Bool {
        lock.withLock { active.contains(identifier) }
    }

    /// NSRecursiveLock lets WebKit synchronously call `stop` from inside a
    /// delivery callback without deadlock. A concurrent stop waits for the
    /// current callback and prevents every subsequent callback.
    func deliver(_ identifier: ObjectIdentifier, _ operation: () -> Void) -> Bool {
        lock.withLock {
            guard active.contains(identifier) else {
                return false
            }
            operation()
            return active.contains(identifier)
        }
    }

    func finish(_ identifier: ObjectIdentifier) {
        lock.withLock {
            _ = active.remove(identifier)
        }
    }
}

private final class SchemeTaskBox: @unchecked Sendable {
    let task: any WKURLSchemeTask

    init(_ task: any WKURLSchemeTask) {
        self.task = task
    }
}

private enum SchemeLoadResult: @unchecked Sendable {
    case success(URLResponse, Data)
    case failure(Error)
}

private extension NSRecursiveLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
