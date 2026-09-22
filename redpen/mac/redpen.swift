// The window the app puts on screen.
//
// redpen's interface is already a local web page, so the Mac app is a window
// onto it: this starts the bundled server on a loopback port nobody else is
// using, waits for it to answer, and shows it.  Nothing is fetched from the
// network, and the server dies with the window.
import AppKit
import WebKit

func freePort() -> UInt16 {
    // Bind port 0, ask the kernel what it gave us, and hand that to the
    // backend.  Racy in principle; the backend falls back to its own search
    // if the port is taken in the moment between here and there.
    let fallback: UInt16 = 8761
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    if fd < 0 { return fallback }
    defer { close(fd) }
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = 0
    addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    let bound = withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    if bound != 0 { return fallback }
    var back = sockaddr_in()
    var len = socklen_t(MemoryLayout<sockaddr_in>.size)
    let got = withUnsafeMutablePointer(to: &back) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            getsockname(fd, $0, &len)
        }
    }
    return got == 0 ? back.sin_port.bigEndian : fallback
}

class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    let port = freePort()

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        let frame = NSRect(x: 0, y: 0, width: 1320, height: 860)
        window = NSWindow(contentRect: frame,
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "redpen"
        window.setFrameAutosaveName("redpenMain")
        window.minSize = NSSize(width: 980, height: 600)

        let cfg = WKWebViewConfiguration()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        web = WKWebView(frame: frame, configuration: cfg)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.uiDelegate = self
        window.contentView = web
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        startBackend()
        waitThenLoad(attempt: 0)
    }

    func startBackend() {
        let res = Bundle.main.resourcePath ?? "."
        let exe = res + "/backend/redpen-backend"
        guard FileManager.default.fileExists(atPath: exe) else {
            show("Cannot find the redpen backend inside the app bundle.")
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exe)
        p.arguments = ["--port", String(port)]
        var env = ProcessInfo.processInfo.environment
        // The bundled typst and poppler, ahead of anything else installed.
        env["PATH"] = res + "/backend/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
        p.environment = env
        do { try p.run() } catch { show("Could not start the backend: \(error)") }
        backend = p
    }

    func waitThenLoad(attempt: Int) {
        let url = URL(string: "http://127.0.0.1:\(port)/")!
        var req = URLRequest(url: url)
        req.timeoutInterval = 1.2
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            DispatchQueue.main.async {
                if (resp as? HTTPURLResponse)?.statusCode == 200 {
                    self.web.load(URLRequest(url: url))
                } else if attempt < 90 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                        self.waitThenLoad(attempt: attempt + 1)
                    }
                } else {
                    self.show("The redpen backend did not start.")
                }
            }
        }.resume()
    }

    // WKWebView does not answer alert/confirm/prompt on its own: without these
    // the page's dialogs silently return "no", which made New Quiz do nothing
    // and every Delete button quietly refuse.  A browser gives these for free;
    // a WKWebView has to be told.
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage msg: String,
                 initiatedByFrame f: WKFrameInfo, completionHandler done: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = "redpen"; a.informativeText = msg
        a.addButton(withTitle: "OK"); a.runModal(); done()
    }

    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage msg: String,
                 initiatedByFrame f: WKFrameInfo,
                 completionHandler done: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = "redpen"; a.informativeText = msg
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        done(a.runModal() == .alertFirstButtonReturn)
    }

    func webView(_ w: WKWebView, runJavaScriptTextInputPanelWithPrompt msg: String,
                 defaultText: String?, initiatedByFrame f: WKFrameInfo,
                 completionHandler done: @escaping (String?) -> Void) {
        let a = NSAlert(); a.messageText = "redpen"; a.informativeText = msg
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 300, height: 24))
        field.stringValue = defaultText ?? ""
        a.accessoryView = field
        a.window.initialFirstResponder = field
        done(a.runModal() == .alertFirstButtonReturn ? field.stringValue : nil)
    }

    // A folder chooser, so picking a quiz folder is the Finder panel rather
    // than a typed path.
    func webView(_ w: WKWebView, runOpenPanelWith params: WKOpenPanelParameters,
                 initiatedByFrame f: WKFrameInfo,
                 completionHandler done: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = params.allowsDirectories ? false : true
        panel.allowsMultipleSelection = params.allowsMultipleSelection
        done(panel.runModal() == .OK ? panel.urls : nil)
    }

    // A link meant for a new window -- the grading page, a spawned editor --
    // opens in the same view rather than vanishing.
    func webView(_ w: WKWebView, createWebViewWith cfg: WKWebViewConfiguration,
                 for action: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let u = action.request.url { w.load(URLRequest(url: u)) }
        return nil
    }

    func show(_ msg: String) {
        let a = NSAlert()
        a.messageText = "redpen"
        a.informativeText = msg
        a.runModal()
    }

    func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About redpen", action: nil, keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r")
        appMenu.addItem(withTitle: "Back", action: #selector(goBack), keyEquivalent: "[")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide redpen", action: #selector(NSApplication.hide(_:)),
                        keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit redpen",
                        action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu

        let editItem = NSMenuItem()
        main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        for (t, s, k) in [("Undo", "undo:", "z"), ("Redo", "redo:", "Z"),
                          ("Cut", "cut:", "x"), ("Copy", "copy:", "c"),
                          ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: t, action: NSSelectorFromString(s), keyEquivalent: k)
        }
        editItem.submenu = edit
        NSApp.mainMenu = main
    }

    @objc func reload() { web.reload() }
    @objc func goBack() { web.goBack() }

    func applicationShouldTerminateAfterLastWindowClosed(_ a: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ note: Notification) { backend?.terminate() }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
