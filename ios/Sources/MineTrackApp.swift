import SwiftUI
import WebKit

@main
struct MineTrackApp: App {
    var body: some Scene {
        WindowGroup {
            MineTrackView()
        }
    }
}

struct MineTrackView: View {
    @State private var loadFailed = false
    @State private var viewID = UUID()

    var body: some View {
        MineTrackWebView { loadFailed = true }
            .id(viewID)
            .overlay {
                if loadFailed {
                    VStack(spacing: 16) {
                        Text("Impossible de charger MineTrack")
                            .font(.headline)
                        Button("Réessayer") {
                            loadFailed = false
                            viewID = UUID()
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Color(uiColor: .systemBackground))
                }
            }
    }
}

private struct MineTrackWebView: UIViewRepresentable {
    static let home = URL(string: "https://project-encua.vercel.app/")!
    let onFailure: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onFailure: onFailure)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.load(URLRequest(url: Self.home))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        private let onFailure: () -> Void

        init(onFailure: @escaping () -> Void) {
            self.onFailure = onFailure
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor action: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard action.targetFrame?.isMainFrame != false,
                  let url = action.request.url else {
                decisionHandler(.allow)
                return
            }
            if url.scheme == "https", url.host == MineTrackWebView.home.host {
                if action.targetFrame == nil {
                    webView.load(action.request)
                    decisionHandler(.cancel)
                } else {
                    decisionHandler(.allow)
                }
                return
            }
            if action.navigationType == .linkActivated,
               ["https", "http", "mailto", "tel"].contains(url.scheme ?? "") {
                UIApplication.shared.open(url)
            }
            decisionHandler(.cancel)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            showFailure(error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            showFailure(error)
        }

        private func showFailure(_ error: Error) {
            let failure = error as NSError
            guard failure.domain != NSURLErrorDomain || failure.code != NSURLErrorCancelled else { return }
            onFailure()
        }
    }
}
