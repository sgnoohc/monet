// The window the app puts on screen.
//
// redpen's interface is already a local web page, so the Mac app is a window
// onto it: this starts the bundled server on a loopback port nobody else is
// using, waits for it to answer, and shows it.  Nothing is fetched from the
// network, and the server dies with the window.
import AppKit
import UniformTypeIdentifiers
import WebKit

func freePort() -> UInt16 {
    // Bind port 0, ask the kernel what it gave us, and hand that to the
    // backend.  Racy in principle; the backend falls back to its own search
    // if the port is taken in the moment between here and there.
    // The same port every launch when it can be had: the grading page keeps
    // its progress in the browser's storage, which is tied to the origin, so
    // a port that changed each time would make every launch look ungraded.
    let fallback: UInt16 = 8761
    for want in [fallback, 0] as [UInt16] {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    if fd < 0 { return fallback }
    defer { close(fd) }
    // A port left in TIME_WAIT by the last launch is free to reuse -- the
    // backend's own server sets SO_REUSEADDR -- but without this the probe
    // calls it taken, and a quick relaunch lands on a random port with the
    // grading progress seemingly gone.
    var one: Int32 = 1
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, socklen_t(MemoryLayout<Int32>.size))
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_port = want.bigEndian
    addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    let bound = withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    if bound != 0 { continue }
    var back = sockaddr_in()
    var len = socklen_t(MemoryLayout<sockaddr_in>.size)
    let got = withUnsafeMutablePointer(to: &back) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            getsockname(fd, $0, &len)
        }
    }
    if got == 0 { return back.sin_port.bigEndian }
    }
    return fallback
}

class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate,
                   WKScriptMessageHandlerWithReply, WKDownloadDelegate {
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
        window.minSize = NSSize(width: 800, height: 520)

        let cfg = WKWebViewConfiguration()
        cfg.preferences.setValue(true, forKey: "developerExtrasEnabled")
        // The page is served by our own backend on loopback, so it is the only
        // thing that can reach this bridge.  It exists because a web view cannot
        // open Finder by itself, and typing an absolute OneDrive path by hand is
        // the worst part of setting the app up.
        cfg.userContentController.addScriptMessageHandler(self, contentWorld: .page,
                                                         name: "redpen")
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

    // A link meant for a new window -- a sheet's PDF from the grading page or
    // the verifier -- gets a window of its own.  Loading it over the main view
    // instead left the sidebar and tabs behind with no way back but the
    // context menu; closing this window (Cmd-W) is the way back now.
    var popups: [NSWindow] = []
    func webView(_ w: WKWebView, createWebViewWith cfg: WKWebViewConfiguration,
                 for action: WKNavigationAction,
                 windowFeatures: WKWindowFeatures) -> WKWebView? {
        let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 980, height: 820),
                           styleMask: [.titled, .closable, .miniaturizable, .resizable],
                           backing: .buffered, defer: false)
        win.title = action.request.url?.lastPathComponent ?? "redpen"
        win.isReleasedWhenClosed = false
        let v = WKWebView(frame: win.contentView!.bounds, configuration: cfg)
        v.autoresizingMask = [.width, .height]
        v.navigationDelegate = self
        v.uiDelegate = self
        win.contentView = v
        win.center()
        win.makeKeyAndOrderFront(nil)
        popups.append(win)
        NotificationCenter.default.addObserver(forName: NSWindow.willCloseNotification,
                                               object: win, queue: .main) { [weak self] _ in
            self?.popups.removeAll { $0 === win }
        }
        return v
    }

    // A page's own window.close() -- honoured for the windows made above.
    func webViewDidClose(_ w: WKWebView) {
        if w !== web { w.window?.close() }
    }

    func webView(_ w: WKWebView, didFinish nav: WKNavigation!) {
        if w !== web, let t = w.title, !t.isEmpty { w.window?.title = t }
    }

    // MARK: - Downloads
    //
    // The grading page hands out files -- Save progress, the grades CSV, the
    // Canvas CSV -- with <a download>.  A bare WKWebView drops those on the
    // floor; these turn them into a Save dialog.
    func webView(_ w: WKWebView, decidePolicyFor action: WKNavigationAction,
                 preferences: WKWebpagePreferences,
                 decisionHandler: @escaping (WKNavigationActionPolicy, WKWebpagePreferences) -> Void) {
        decisionHandler(action.shouldPerformDownload ? .download : .allow, preferences)
    }
    func webView(_ w: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }
    func webView(_ w: WKWebView, navigationAction: WKNavigationAction, didBecome d: WKDownload) {
        d.delegate = self
    }
    func webView(_ w: WKWebView, navigationResponse: WKNavigationResponse, didBecome d: WKDownload) {
        d.delegate = self
    }
    func download(_ d: WKDownload, decideDestinationUsing r: URLResponse,
                  suggestedFilename name: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = name
        panel.canCreateDirectories = true
        panel.beginSheetModal(for: window) { resp in
            guard resp == .OK, let url = panel.url else { completionHandler(nil); return }
            // WKDownload refuses a destination that already exists: without
            // this, choosing Replace in the panel failed the download and left
            // the old file in place -- an earlier export, unscaled, that looked
            // like the new one.  The panel has already asked about replacing.
            if FileManager.default.fileExists(atPath: url.path) {
                do { try FileManager.default.removeItem(at: url) }
                catch { self.show("Could not replace \(url.lastPathComponent): \(error.localizedDescription)")
                        completionHandler(nil); return }
            }
            completionHandler(url)
        }
    }
    func download(_ d: WKDownload, didFailWithError e: Error, resumeData: Data?) {
        show("Could not save the file: \(e.localizedDescription)")
    }

    // MARK: - Finder bridge
    //
    // JS calls  await window.webkit.messageHandlers.redpen.postMessage({op:"folder"})
    // and gets back an array of absolute paths -- empty if the panel was cancelled,
    // which the page treats as "nothing chosen" rather than as an error.
    func userContentController(_ ucc: WKUserContentController,
                               didReceive message: WKScriptMessage,
                               replyHandler: @escaping (Any?, String?) -> Void) {
        guard let body = message.body as? [String: Any],
              let op = body["op"] as? String else {
            replyHandler(nil, "redpen: malformed request"); return
        }

        let panel = NSOpenPanel()
        panel.message = body["message"] as? String ?? "Choose"
        panel.prompt = "Choose"
        panel.showsHiddenFiles = false

        switch op {
        case "folder":
            panel.canChooseDirectories = true
            panel.canChooseFiles = false
            panel.allowsMultipleSelection = false
        case "files":
            panel.canChooseDirectories = false
            panel.canChooseFiles = true
            panel.allowsMultipleSelection = true
            // Filtered to what the page asked for: PDFs for scans, CSV for the roster.
            if let exts = body["exts"] as? [String] {
                let types = exts.compactMap { UTType(filenameExtension: $0) }
                if !types.isEmpty { panel.allowedContentTypes = types }
            }
        default:
            replyHandler(nil, "redpen: unknown op \(op)"); return
        }

        // A sheet, not a free-floating dialog: it belongs to this window.
        panel.beginSheetModal(for: window) { resp in
            guard resp == .OK else { replyHandler([String](), nil); return }
            replyHandler(panel.urls.map { $0.path }, nil)
        }
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
        // Reads CFBundleShortVersionString out of Info.plist, so the window can
        // always say which build it is -- the question every redeploy raises.
        appMenu.addItem(withTitle: "About redpen",
                        action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
                        keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r")
        appMenu.addItem(withTitle: "Back", action: #selector(goBack), keyEquivalent: "[")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide redpen", action: #selector(NSApplication.hide(_:)),
                        keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit redpen",
                        action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu

        // Window menu: Cmd-W closes a PDF window and leaves the app.
        let winItem = NSMenuItem()
        let winMenu = NSMenu(title: "Window")
        winMenu.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)),
                        keyEquivalent: "w")
        winMenu.addItem(withTitle: "Minimize",
                        action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        winItem.submenu = winMenu

        let editItem = NSMenuItem()
        main.addItem(editItem)
        let edit = NSMenu(title: "Edit")
        for (t, s, k) in [("Undo", "undo:", "z"), ("Redo", "redo:", "Z"),
                          ("Cut", "cut:", "x"), ("Copy", "copy:", "c"),
                          ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: t, action: NSSelectorFromString(s), keyEquivalent: k)
        }
        editItem.submenu = edit
        main.addItem(winItem)
        NSApp.windowsMenu = winMenu
        NSApp.mainMenu = main
    }

    // Whichever window is in front, so Back and Reload act on what you see.
    var front: WKWebView { (NSApp.keyWindow?.contentView as? WKWebView) ?? web }
    @objc func reload() { front.reload() }
    @objc func goBack() { front.goBack() }

    func applicationShouldTerminateAfterLastWindowClosed(_ a: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ note: Notification) { backend?.terminate() }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
