import AppKit
import SimulatorBridge

@MainActor
final class ApplicationEnvironment {
    static let shared = ApplicationEnvironment()

    let lifecycle: RunnerLifecycle
    let manager: SimulatorManager
    let webRoot: Result<URL, Error>

    private init() {
        let lifecycle = RunnerLifecycle()
        self.lifecycle = lifecycle
        self.manager = SimulatorManager(
            runnerDirectory: AppResourceLocator.runnerDirectory(),
            lifecycle: lifecycle
        )
        self.webRoot = Result { try AppResourceLocator.webRoot() }
    }
}

@MainActor
final class ApplicationDelegate: NSObject, NSApplicationDelegate {
    func applicationWillTerminate(_ notification: Notification) {
        ApplicationEnvironment.shared.lifecycle.terminatePermanently()
    }
}
