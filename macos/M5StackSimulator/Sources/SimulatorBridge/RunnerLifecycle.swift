import Foundation

/// A synchronous termination hook shared with NSApplicationDelegate. It makes
/// child cleanup reliable even when the Swift concurrency runtime is already
/// winding down during application termination.
public final class RunnerLifecycle: @unchecked Sendable {
    private let lock = NSLock()
    private var runner: NativeRunnerProcess?
    private var acceptsNewRunners = true

    public init() {}

    @discardableResult
    public func replace(with newRunner: NativeRunnerProcess?) -> Bool {
        let result: (accepted: Bool, previous: NativeRunnerProcess?) = lock.withLock {
            guard acceptsNewRunners || newRunner == nil else {
                return (false, nil)
            }
            let previous = runner
            runner = newRunner
            return (true, previous)
        }
        guard result.accepted else {
            newRunner?.stop()
            return false
        }
        if result.previous !== newRunner {
            result.previous?.stop()
        }
        return true
    }

    public func current() -> NativeRunnerProcess? {
        lock.withLock { runner }
    }

    public func shutdown() {
        replace(with: nil)
    }

    /// Permanently closes the lifecycle gate during NSApplication teardown.
    /// This prevents an in-flight firmware switch from installing a new child
    /// after applicationWillTerminate has already cleaned up the old one.
    public func terminatePermanently() {
        let previous = lock.withLock {
            acceptsNewRunners = false
            let previous = runner
            runner = nil
            return previous
        }
        previous?.stop()
    }
}

private extension NSLock {
    func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock()
        defer { unlock() }
        return try operation()
    }
}
