import AppKit
import SimulatorBridge
import SwiftUI
import UniformTypeIdentifiers
import WebKit

struct SimulatorWebView: NSViewRepresentable {
    let webRoot: URL
    let manager: SimulatorManager

    func makeCoordinator() -> Coordinator {
        Coordinator(webRoot: webRoot, manager: manager)
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.setURLSchemeHandler(context.coordinator.schemeHandler, forURLScheme: "m5sim")
        configuration.userContentController.addScriptMessageHandler(
            context.coordinator.bridgeHandler,
            contentWorld: .page,
            name: "m5sim"
        )
        configuration.userContentController.addUserScript(
            WKUserScript(
                source: NativeBridgeHandler.bootstrapJavaScript,
                injectionTime: .atDocumentStart,
                forMainFrameOnly: true,
                in: .page
            )
        )

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsMagnification = false
        webView.underPageBackgroundColor = .clear
        webView.load(URLRequest(url: URL(string: "m5sim://app/index.html")!))

        Task {
            _ = try? await manager.snapshot()
        }
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKDownloadDelegate {
        let schemeHandler: WebSchemeHandler
        let bridgeHandler: NativeBridgeHandler

        init(webRoot: URL, manager: SimulatorManager) {
            self.schemeHandler = WebSchemeHandler(webRoot: webRoot)
            self.bridgeHandler = NativeBridgeHandler(manager: manager)
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
        ) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }
            if ScreenshotDownloadPolicy.allowsNavigation(
                url: url,
                shouldPerformDownload: navigationAction.shouldPerformDownload
            ) {
                decisionHandler(.download)
            } else if url.scheme == "m5sim" && url.host == "app" {
                decisionHandler(.allow)
            } else if navigationAction.navigationType == .linkActivated,
                      let scheme = url.scheme,
                      scheme == "https" || scheme == "http"
            {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.cancel)
            }
        }

        func webView(
            _ webView: WKWebView,
            navigationAction: WKNavigationAction,
            didBecome download: WKDownload
        ) {
            download.delegate = self
        }

        func webView(
            _ webView: WKWebView,
            navigationResponse: WKNavigationResponse,
            didBecome download: WKDownload
        ) {
            download.delegate = self
        }

        func download(
            _ download: WKDownload,
            decideDestinationUsing response: URLResponse,
            suggestedFilename: String,
            completionHandler: @escaping @MainActor @Sendable (URL?) -> Void
        ) {
            guard ScreenshotDownloadPolicy.allowsResponse(
                mimeType: response.mimeType,
                expectedContentLength: response.expectedContentLength
            ) else {
                completionHandler(nil)
                return
            }

            // No web-selected path is trusted. A native save panel makes the
            // screenshot destination an explicit user action and preserves
            // normal macOS overwrite confirmation.
            let panel = NSSavePanel()
            panel.nameFieldStringValue = ScreenshotDownloadPolicy.safeFilename(suggestedFilename)
            panel.allowedContentTypes = [.png]
            panel.canCreateDirectories = true
            panel.isExtensionHidden = false
            if let window = NSApp.keyWindow {
                panel.beginSheetModal(for: window) { result in
                    completionHandler(result == .OK ? panel.url : nil)
                }
            } else {
                panel.begin { result in
                    completionHandler(result == .OK ? panel.url : nil)
                }
            }
        }
    }
}
