import SwiftUI

@main
struct M5StackSimulatorApp: App {
    @NSApplicationDelegateAdaptor(ApplicationDelegate.self) private var appDelegate

    private let environment = ApplicationEnvironment.shared

    var body: some Scene {
        WindowGroup("M5Stack Simulator") {
            Group {
                switch environment.webRoot {
                case let .success(webRoot):
                    SimulatorWebView(webRoot: webRoot, manager: environment.manager)
                case let .failure(error):
                    MissingAssetsView(message: error.localizedDescription)
                }
            }
            .background(WindowConfigurationView())
            .frame(minWidth: 1_120, minHeight: 760)
        }
        .defaultSize(width: 1_440, height: 900)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}

private struct MissingAssetsView: View {
    let message: String

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "shippingbox")
                .font(.system(size: 42, weight: .light))
                .foregroundStyle(.secondary)
            Text("Workbench assets are not installed")
                .font(.title2.weight(.semibold))
            Text(message)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 520)
        }
        .padding(48)
    }
}

private struct WindowConfigurationView: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView(frame: .zero)
        DispatchQueue.main.async { configure(view.window) }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async { configure(nsView.window) }
    }

    private func configure(_ window: NSWindow?) {
        guard let window else { return }
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.titlebarSeparatorStyle = .none
        window.styleMask.insert(.fullSizeContentView)
        window.toolbarStyle = .unifiedCompact
        window.isMovableByWindowBackground = false
        window.collectionBehavior.insert(.fullScreenPrimary)
    }
}
