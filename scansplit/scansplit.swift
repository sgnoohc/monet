// scansplit — split a bulk scan into one PDF per student, named from the
// handwriting on each sheet and matched against a Canvas roster.
//
// Everything runs on this Mac: PDFKit reads and writes the PDFs, Apple's Vision
// framework reads the names.  The matching is redpen's (../redpen/redpen/
// matching.py) ported across: every sheet is scored against every roster name,
// then the sheet -> student mapping is solved as an assignment problem, so a
// badly read sheet still lands on the one student nobody else claimed.
//
//   scansplit                      the app
//   scansplit --scan bulk.pdf ...  the same pipeline from the command line
import AppKit
import PDFKit
import SwiftUI
import UniformTypeIdentifiers
import Vision

// MARK: - Roster

struct Student: Identifiable, Hashable {
    let id: Int              // index into the roster
    let first: String
    let last: String

    var display: String { first.isEmpty ? last : "\(last), \(first)" }

    /// LastName_FirstName, accent-free and filename-safe.
    var fileKey: String {
        let l = filePart(last), f = filePart(first)
        return f.isEmpty ? (l.isEmpty ? "student" : l) : "\(l)_\(f)"
    }
}

func fold(_ s: String) -> String {
    s.applyingTransform(.stripDiacritics, reverse: false) ?? s
}

func filePart(_ s: String) -> String {
    String(fold(s).unicodeScalars.filter {
        CharacterSet.alphanumerics.contains($0) || $0 == "-"
    }.map(Character.init))
}

func parseCSV(_ text: String) -> [[String]] {
    var rows: [[String]] = [], row: [String] = [], field = "", quoted = false
    // Swift reads "\r\n" as one Character, so normalise line ends first.
    let chars = Array(text.replacingOccurrences(of: "\r\n", with: "\n")
                          .replacingOccurrences(of: "\r", with: "\n"))
    var i = 0
    while i < chars.count {
        let c = chars[i]
        if quoted {
            if c == "\"" {
                if i + 1 < chars.count && chars[i + 1] == "\"" { field.append("\""); i += 1 }
                else { quoted = false }
            } else { field.append(c) }
        } else {
            switch c {
            case "\"": quoted = true
            case ",": row.append(field); field = ""
            case "\n": row.append(field); rows.append(row); row = []; field = ""
            default: field.append(c)
            }
        }
        i += 1
    }
    if !field.isEmpty || !row.isEmpty { row.append(field); rows.append(row) }
    return rows
}

enum RosterError: LocalizedError {
    case unreadable, empty
    var errorDescription: String? {
        switch self {
        case .unreadable: return "can't read that file"
        case .empty: return "no student names found"
        }
    }
}

/// A Canvas gradebook export ("Student" column, "Last, First"), a Canvas
/// people list, or any CSV with a name column or first/last name columns.
func loadRoster(_ url: URL) throws -> [Student] {
    guard let data = try? Data(contentsOf: url),
          let text = String(data: data, encoding: .utf8) ?? String(data: data, encoding: .isoLatin1)
    else { throw RosterError.unreadable }
    let rows = parseCSV(text.hasPrefix("\u{FEFF}") ? String(text.dropFirst()) : text)
    guard let head = rows.first else { throw RosterError.empty }
    let h = head.map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
    func cell(_ r: [String], _ i: Int) -> String {
        i < r.count ? r[i].trimmingCharacters(in: .whitespaces) : ""
    }
    var pairs: [(String, String)] = []

    if let li = h.firstIndex(where: { $0 == "last name" || $0 == "last" || $0 == "surname" }),
       let fi = h.firstIndex(where: { $0 == "first name" || $0 == "first" || $0 == "given name" }) {
        for r in rows.dropFirst() where !cell(r, li).isEmpty {
            pairs.append((cell(r, fi), cell(r, li)))
        }
    } else {
        let names = ["student", "name", "student name", "sortable name", "full name"]
        let col = h.firstIndex(where: names.contains)
        let skip: Set<String> = Set(names + ["points possible", "students"])
        for r in rows.dropFirst(col == nil ? 0 : 1) {
            let raw = cell(r, col ?? 0)
            let low = raw.lowercased()
            if raw.isEmpty || skip.contains(low) || low == "student, test" || low == "test student" {
                continue
            }
            if let comma = raw.firstIndex(of: ",") {
                pairs.append((raw[raw.index(after: comma)...].trimmingCharacters(in: .whitespaces),
                              raw[..<comma].trimmingCharacters(in: .whitespaces)))
            } else {
                let bits = raw.split(separator: " ").map(String.init)
                pairs.append((bits.dropLast().joined(separator: " "), bits.last ?? raw))
            }
        }
    }
    guard !pairs.isEmpty else { throw RosterError.empty }
    return pairs.enumerated().map { Student(id: $0.offset, first: $0.element.0, last: $0.element.1) }
}

/// Names Vision should prefer when a scrawl could be read either way.
func customWords(_ roster: [Student]) -> [String] {
    var w = Set<String>()
    for s in roster {
        w.formUnion([s.first, s.last, fold(s.first), fold(s.last),
                     "\(s.first) \(s.last)", "\(s.last) \(s.first)"])
    }
    return w.filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.sorted()
}

// MARK: - Scoring and assignment

func tokens(_ s: String) -> [String] {
    fold(s).lowercased().split(whereSeparator: { !$0.isLetter }).map(String.init).filter { $0.count > 1 }
}

/// Python's difflib.SequenceMatcher(None, a, b).ratio(), which redpen's
/// thresholds were tuned against.
func ratio(_ a: String, _ b: String) -> Double {
    let x = Array(a), y = Array(b)
    let total = x.count + y.count
    guard total > 0 else { return 1 }
    return 2 * Double(matched(x, 0, x.count, y, 0, y.count)) / Double(total)
}

private func matched(_ a: [Character], _ alo: Int, _ ahi: Int,
                     _ b: [Character], _ blo: Int, _ bhi: Int) -> Int {
    guard alo < ahi, blo < bhi else { return 0 }
    var best = 0, bi = alo, bj = blo
    var prev = [Int](repeating: 0, count: bhi - blo + 1)
    for i in alo..<ahi {
        var cur = [Int](repeating: 0, count: bhi - blo + 1)
        for j in blo..<bhi where a[i] == b[j] {
            let k = prev[j - blo] + 1
            cur[j - blo + 1] = k
            if k > best { best = k; bi = i - k + 1; bj = j - k + 1 }
        }
        prev = cur
    }
    guard best > 0 else { return 0 }
    return best + matched(a, alo, bi, b, blo, bj) + matched(a, bi + best, ahi, b, bj + best, bhi)
}

/// Similarity in [0, 1] between a sheet's OCR readings and one student.
func score(_ readings: [String], _ s: Student) -> Double {
    let forms = ["\(s.first) \(s.last)", "\(s.last) \(s.first)", s.last, s.first]
    var best = 0.0
    for c in readings {
        let ct = tokens(c)
        if ct.isEmpty { continue }
        let joined = ct.joined(separator: " ")
        for f in forms {
            let ft = tokens(f)
            if ft.isEmpty { continue }
            best = max(best, ratio(joined, ft.joined(separator: " ")))
            for a in ct {                 // a surname alone is strong evidence
                for b in ft where b.count > 3 {
                    best = max(best, 0.92 * ratio(a, b))
                }
            }
        }
    }
    return best
}

/// Minimum-cost assignment (rows <= cols).  Returns the column for each row.
func hungarian(_ cost: [[Double]]) -> [Int] {
    let n = cost.count
    guard n > 0 else { return [] }
    let m = cost[0].count
    var u = [Double](repeating: 0, count: n + 1), v = [Double](repeating: 0, count: m + 1)
    var p = [Int](repeating: 0, count: m + 1), way = [Int](repeating: 0, count: m + 1)
    for i in 1...n {
        p[0] = i
        var j0 = 0
        var minv = [Double](repeating: .infinity, count: m + 1)
        var used = [Bool](repeating: false, count: m + 1)
        repeat {
            used[j0] = true
            let i0 = p[j0]
            var delta = Double.infinity, j1 = 0
            for j in 1...m where !used[j] {
                let cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j] { minv[j] = cur; way[j] = j0 }
                if minv[j] < delta { delta = minv[j]; j1 = j }
            }
            for j in 0...m {
                if used[j] { u[p[j]] += delta; v[j] -= delta } else { minv[j] -= delta }
            }
            j0 = j1
        } while p[j0] != 0
        repeat {
            let j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
        } while j0 != 0
    }
    var out = [Int](repeating: -1, count: n)
    for j in 1...m where p[j] != 0 { out[p[j] - 1] = j - 1 }
    return out
}

// A sheet whose best score is below this, or that beats its runner-up by less
// than the gap, is flagged for a look.  redpen's defaults.
let reviewScore = 0.55
let reviewGap = 0.10

struct Sheet: Identifiable {
    let id: Int              // 0-based sheet number
    let pages: [Int]         // 0-based page indexes in the scan
    let crop: CGImage?
    let readings: [String]
    var scores: [Double] = []
    var auto = -1            // roster index the matcher chose; -1 = none
    var choice = -1          // roster index that will be written
    var score = 0.0
    var gap = 0.0
    var flags: [String] = []
}

func assign(_ sheets: inout [Sheet], _ roster: [Student]) {
    guard !sheets.isEmpty, !roster.isEmpty else { return }
    for i in sheets.indices {
        sheets[i].scores = roster.map { score(sheets[i].readings, $0) }
    }
    // More sheets than students: pad with "nobody" columns so the extras come
    // out unmatched instead of stealing a name.
    let pad = max(0, sheets.count - roster.count)
    let cost = sheets.map { $0.scores.map { 1 - $0 } + [Double](repeating: 1, count: pad) }
    let pick = hungarian(cost)
    for i in sheets.indices {
        let j = pick[i] < roster.count ? pick[i] : -1
        var s = sheets[i]
        s.auto = j
        s.choice = j
        s.flags = []
        if s.readings.isEmpty { s.flags.append("nothing read") }
        if j < 0 {
            s.flags.append("no student left to match")
        } else {
            s.score = s.scores[j]
            let runner = s.scores.enumerated().filter { $0.offset != j }.max { $0.element < $1.element }
            s.gap = s.score - (runner?.element ?? 0)
            if s.score < reviewScore { s.flags.append(String(format: "weak read (%.2f)", s.score)) }
            if let r = runner, s.gap < reviewGap {
                s.flags.append("close to \(roster[r.offset].display)")
            }
        }
        sheets[i] = s
    }
}

// MARK: - Rendering and OCR

/// The displayed size of a page, rotation included, in points.
func displaySize(_ page: PDFPage) -> CGSize {
    let b = page.bounds(for: .mediaBox)
    return (page.rotation % 180 == 0) ? b.size : CGSize(width: b.height, height: b.width)
}

/// Render part of a page.  `rect` is a fraction of the displayed page, origin
/// top-left, so it holds for any page size or scan resolution.  The region
/// picker previews with this same function, so what you box is what is read.
func render(_ page: PDFPage, _ rect: CGRect = CGRect(x: 0, y: 0, width: 1, height: 1),
            dpi: CGFloat) -> CGImage? {
    let size = displaySize(page)
    let s = dpi / 72
    let w = max(1, Int((rect.width * size.width * s).rounded()))
    let h = max(1, Int((rect.height * size.height * s).rounded()))
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                              space: CGColorSpace(name: CGColorSpace.sRGB)!,
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { return nil }
    ctx.setFillColor(.white)
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.interpolationQuality = .high
    ctx.scaleBy(x: s, y: s)
    ctx.translateBy(x: -rect.minX * size.width, y: -(1 - rect.maxY) * size.height)
    page.draw(with: .mediaBox, to: ctx)
    return ctx.makeImage()
}

// A clipped "Name:" caption at the start of a reading — not "15." or a surname.
private let captionPattern = try! NSRegularExpression(pattern: #"^\s*[A-Za-z]{0,4}:\s*"#)

func recognize(_ image: CGImage, words: [String]) -> [String] {
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false        // proper names are not dictionary words
    req.recognitionLanguages = ["en-US"]
    req.customWords = words
    try? VNImageRequestHandler(cgImage: image, options: [:]).perform([req])
    var out: [String] = []
    for obs in req.results ?? [] {
        for cand in obs.topCandidates(3) {
            let ns = cand.string as NSString
            let t = captionPattern.stringByReplacingMatches(
                in: cand.string, range: NSRange(location: 0, length: ns.length), withTemplate: "")
                .trimmingCharacters(in: .whitespaces)
            if t.count > 1, t.lowercased() != "name", t.contains(where: { $0.isLetter }) {
                out.append(t)
            }
        }
    }
    return out
}

let ocrDPI: CGFloat = 400

/// Read the name region of every sheet in the scan.
func readSheets(_ doc: PDFDocument, perStudent: Int, namePage: Int, rect: CGRect,
                words: [String], progress: @escaping (Int, Int) -> Void) -> [Sheet] {
    let n = doc.pageCount / perStudent
    var crops = [CGImage?](repeating: nil, count: n)
    // PDFKit is rendered from one thread; Vision then reads the crops in parallel.
    for k in 0..<n {
        autoreleasepool {
            if let page = doc.page(at: k * perStudent + namePage - 1) {
                crops[k] = render(page, rect, dpi: ocrDPI)
            }
        }
    }
    var readings = [[String]](repeating: [], count: n)
    let lock = NSLock()
    var done = 0
    DispatchQueue.concurrentPerform(iterations: n) { k in
        let r = crops[k].map { recognize($0, words: words) } ?? []
        lock.lock()
        readings[k] = r
        done += 1
        let d = done
        lock.unlock()
        progress(d, n)
    }
    return (0..<n).map { k in
        Sheet(id: k, pages: Array(k * perStudent ..< (k + 1) * perStudent),
              crop: crops[k], readings: readings[k])
    }
}

/// The filename each sheet will be written under, in sheet order.
func fileNames(_ sheets: [Sheet], _ roster: [Student]) -> [String] {
    var used: [String: Int] = [:]
    return sheets.map { s in
        var base = s.choice >= 0 ? roster[s.choice].fileKey
                                 : String(format: "Unmatched_sheet%02d", s.id + 1)
        // Two students with identical names still get two files.
        let n = (used[base] ?? 0) + 1
        used[base] = n
        if n > 1 { base += "_\(n)" }
        return base + ".pdf"
    }
}

enum WriteError: LocalizedError {
    case failed(String)
    var errorDescription: String? {
        if case .failed(let f) = self { return "couldn't write \(f)" }
        return nil
    }
}

func writeSheets(_ doc: PDFDocument, _ sheets: [Sheet], _ roster: [Student], to dir: URL) throws -> [URL] {
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    var urls: [URL] = []
    for (s, name) in zip(sheets, fileNames(sheets, roster)) {
        let out = PDFDocument()
        for (i, p) in s.pages.enumerated() {
            if let page = doc.page(at: p)?.copy() as? PDFPage { out.insert(page, at: i) }
        }
        let url = dir.appendingPathComponent(name)
        guard out.write(to: url) else { throw WriteError.failed(name) }
        urls.append(url)
    }
    return urls
}

// MARK: - Command line

func runCLI(_ args: [String]) -> Int32 {
    func value(_ flag: String) -> String? {
        guard let i = args.firstIndex(of: flag), i + 1 < args.count else { return nil }
        return args[i + 1]
    }
    let usage = """
        usage: scansplit --scan bulk.pdf --roster roster.csv --pages N --rect x,y,w,h
                         [--name-page P] [--out DIR] [--crops DIR]

          --rect       the name region as fractions of the page, origin top-left
          --name-page  which page of each student's set holds the name (default 1)
          --out        write LastName_FirstName.pdf files here (else: report only)
          --crops      also save each sheet's name crop as a PNG, to check the region
        """
    if args.contains("--help") { print(usage); return 0 }
    guard let scan = value("--scan"), let rosterPath = value("--roster"),
          let per = value("--pages").flatMap(Int.init), per > 0,
          let rectText = value("--rect") else {
        FileHandle.standardError.write(usage.data(using: .utf8)!)
        return 2
    }
    let r = rectText.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
    guard r.count == 4 else { print("--rect wants four numbers: x,y,w,h"); return 2 }
    let rect = CGRect(x: r[0], y: r[1], width: r[2], height: r[3])
    let namePage = value("--name-page").flatMap(Int.init) ?? 1

    guard let doc = PDFDocument(url: URL(fileURLWithPath: scan)) else { print("can't open \(scan)"); return 1 }
    if doc.pageCount % per != 0 {
        print("\(scan) has \(doc.pageCount) pages, not a multiple of \(per) — a sheet was probably mis-fed")
        return 1
    }
    let roster: [Student]
    do { roster = try loadRoster(URL(fileURLWithPath: rosterPath)) } catch {
        print("roster: \(error.localizedDescription)"); return 1
    }
    print("\(doc.pageCount) pages -> \(doc.pageCount / per) sheets, \(roster.count) students on the roster")
    var sheets = readSheets(doc, perStudent: per, namePage: namePage, rect: rect,
                            words: customWords(roster)) { _, _ in }
    assign(&sheets, roster)

    if let dir = value("--crops") {
        let d = URL(fileURLWithPath: dir)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        for s in sheets {
            if let c = s.crop, let data = NSBitmapImageRep(cgImage: c).representation(using: .png, properties: [:]) {
                try? data.write(to: d.appendingPathComponent(String(format: "sheet%02d.png", s.id + 1)))
            }
        }
    }
    let names = fileNames(sheets, roster)
    for (s, name) in zip(sheets, names) {
        let read = s.readings.first ?? "—"
        let flag = s.flags.isEmpty ? "" : "   [\(s.flags.joined(separator: "; "))]"
        print(String(format: "  #%02d  p%d-%d  %.2f  ", s.id + 1, s.pages.first! + 1, s.pages.last! + 1, s.score)
              + "\(name.padding(toLength: 28, withPad: " ", startingAt: 0)) read \"\(read)\"\(flag)")
    }
    let seen = Set(sheets.map(\.choice))
    let absent = roster.filter { !seen.contains($0.id) }
    if !absent.isEmpty { print("no sheet for: " + absent.map(\.display).joined(separator: "; ")) }
    let flagged = sheets.filter { !$0.flags.isEmpty }.count
    print("\(sheets.count - flagged) confident, \(flagged) flagged")

    if let dir = value("--out") {
        do {
            let urls = try writeSheets(doc, sheets, roster, to: URL(fileURLWithPath: dir))
            print("wrote \(urls.count) files to \(dir)")
        } catch { print(error.localizedDescription); return 1 }
    }
    return 0
}

// MARK: - App model

/// The one window shows one of these at a time.
enum Screen { case setup, region, review }

final class Model: ObservableObject {
    @Published var screen = Screen.setup
    @Published var scanURL: URL?
    @Published var doc: PDFDocument?
    @Published var rosterURL: URL?
    @Published var roster: [Student] = []
    @Published var rosterError: String?

    // The settings a worksheet keeps from week to week are remembered.
    @Published var perStudent: Int { didSet { defaults.set(perStudent, forKey: "perStudent") } }
    @Published var namePage: Int { didSet { defaults.set(namePage, forKey: "namePage") } }
    @Published var nameRect: CGRect? {
        didSet {
            defaults.set(nameRect.map { "\($0.minX),\($0.minY),\($0.width),\($0.height)" }, forKey: "nameRect")
        }
    }
    @Published var outDir: URL? { didSet { defaults.set(outDir?.path, forKey: "outDir") } }

    @Published var busy = false
    @Published var progress = 0.0
    @Published var status = ""
    @Published var sheets: [Sheet] = []
    @Published var saved: [URL] = []

    private let defaults = UserDefaults.standard

    init() {
        perStudent = max(1, defaults.integer(forKey: "perStudent"))
        namePage = max(1, defaults.integer(forKey: "namePage"))
        if let s = defaults.string(forKey: "nameRect") {
            let v = s.split(separator: ",").compactMap { Double($0) }
            if v.count == 4 { nameRect = CGRect(x: v[0], y: v[1], width: v[2], height: v[3]) }
        }
        if let p = defaults.string(forKey: "outDir") { outDir = URL(fileURLWithPath: p) }
    }

    var pageCount: Int { doc?.pageCount ?? 0 }
    var sheetCount: Int { pageCount / perStudent }

    var pageProblem: String? {
        guard doc != nil else { return nil }
        if pageCount % perStudent != 0 {
            return "\(pageCount) pages isn't a multiple of \(perStudent) — a sheet may have been mis-fed"
        }
        return nil
    }

    var ready: Bool {
        doc != nil && !roster.isEmpty && nameRect != nil && pageProblem == nil && namePage <= perStudent
    }

    /// Roster indexes chosen by more than one sheet.
    var duplicates: Set<Int> {
        var seen = Set<Int>(), dup = Set<Int>()
        for s in sheets where s.choice >= 0 {
            if !seen.insert(s.choice).inserted { dup.insert(s.choice) }
        }
        return dup
    }

    var absent: [Student] {
        let taken = Set(sheets.map(\.choice))
        return roster.filter { !taken.contains($0.id) }
    }

    func openScan(_ url: URL) {
        guard let d = PDFDocument(url: url) else { status = "Can't open \(url.lastPathComponent)"; return }
        scanURL = url
        doc = d
        sheets = []
        saved = []
        if screen == .review { screen = .setup }
        if outDir == nil { outDir = url.deletingLastPathComponent() }
    }

    func openRoster(_ url: URL) {
        rosterURL = url
        do {
            roster = try loadRoster(url)
            rosterError = nil
        } catch {
            roster = []
            rosterError = error.localizedDescription
        }
        sheets = []
        if screen == .review { screen = .setup }
    }

    func chooseOutDir() {
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.canCreateDirectories = true
        p.prompt = "Choose"
        p.message = "Where should the student PDFs go?"
        p.directoryURL = outDir
        if p.runModal() == .OK, let u = p.url { outDir = u }
    }

    func run(then done: @escaping () -> Void) {
        guard ready, let url = scanURL, let rect = nameRect else { return }
        busy = true
        progress = 0
        saved = []
        status = "Reading names…"
        let per = perStudent, page = namePage, roster = roster
        DispatchQueue.global(qos: .userInitiated).async {
            // A document of its own, so the region window can keep rendering.
            guard let doc = PDFDocument(url: url) else { return }
            var sheets = readSheets(doc, perStudent: per, namePage: page, rect: rect,
                                    words: customWords(roster)) { d, n in
                DispatchQueue.main.async {
                    self.progress = Double(d) / Double(n)
                    self.status = "Reading names \(d) of \(n)"
                }
            }
            assign(&sheets, roster)
            DispatchQueue.main.async {
                self.sheets = sheets
                self.busy = false
                let flagged = sheets.filter { !$0.flags.isEmpty }.count
                self.status = "\(sheets.count) sheets read" + (flagged > 0 ? ", \(flagged) to check" : "")
                done()
            }
        }
    }

    func save() {
        guard let doc, let dir = outDir, duplicates.isEmpty else { return }
        let names = fileNames(sheets, roster)
        let existing = names.filter { FileManager.default.fileExists(atPath: dir.appendingPathComponent($0).path) }
        if !existing.isEmpty {
            let a = NSAlert()
            a.messageText = "Replace \(existing.count) existing file\(existing.count == 1 ? "" : "s")?"
            a.informativeText = existing.prefix(6).joined(separator: "\n") + (existing.count > 6 ? "\n…" : "")
            a.addButton(withTitle: "Replace")
            a.addButton(withTitle: "Cancel")
            if a.runModal() != .alertFirstButtonReturn { return }
        }
        do {
            saved = try writeSheets(doc, sheets, roster, to: dir)
            status = "Saved \(saved.count) PDFs to \(dir.lastPathComponent)"
        } catch {
            status = error.localizedDescription
        }
    }
}

// MARK: - Views

struct DropZone: View {
    let title: String
    let symbol: String
    let detail: String?
    let problem: String?
    let types: [UTType]
    let pick: (URL) -> Void
    @State private var targeted = false

    var body: some View {
        let filled = detail != nil
        VStack(spacing: 4) {
            Image(systemName: filled ? "checkmark.circle.fill" : symbol)
                .font(.system(size: 22))
                .foregroundStyle(problem != nil ? Color.orange : filled ? Color.green : Color.secondary)
            Text(title).font(.headline)
            Text(problem ?? detail ?? "Drop here or click")
                .font(.caption)
                .foregroundStyle(problem != nil ? Color.orange : Color.secondary)
                .lineLimit(2)
                .multilineTextAlignment(.center)
        }
        .padding(8)
        .frame(maxWidth: .infinity, minHeight: 100)
        .background(RoundedRectangle(cornerRadius: 10)
            .fill(targeted ? Color.accentColor.opacity(0.15) : Color.secondary.opacity(0.06)))
        .overlay(RoundedRectangle(cornerRadius: 10)
            .strokeBorder(targeted ? Color.accentColor : Color.secondary.opacity(0.45),
                          style: StrokeStyle(lineWidth: 1.5, dash: filled ? [] : [5, 4])))
        .contentShape(Rectangle())
        .onTapGesture(perform: browse)
        .dropDestination(for: URL.self) { urls, _ in
            guard let u = urls.first(where: accepts) else { return false }
            pick(u)
            return true
        } isTargeted: { targeted = $0 }
        .help(detail ?? "Drop a file here, or click to choose one")
    }

    func accepts(_ u: URL) -> Bool {
        guard let t = UTType(filenameExtension: u.pathExtension) else { return false }
        return types.contains { t.conforms(to: $0) }
    }

    func browse() {
        let p = NSOpenPanel()
        p.allowedContentTypes = types
        p.allowsMultipleSelection = false
        if p.runModal() == .OK, let u = p.url { pick(u) }
    }
}

struct MainView: View {
    @EnvironmentObject var m: Model

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                DropZone(title: "Bulk scan", symbol: "doc.viewfinder",
                         detail: m.scanURL.map { "\($0.lastPathComponent)\n\(m.pageCount) pages" },
                         problem: nil, types: [.pdf]) { m.openScan($0) }
                DropZone(title: "Canvas roster", symbol: "person.3",
                         detail: m.rosterURL.map { "\($0.lastPathComponent)\n\(m.roster.count) students" },
                         problem: m.rosterError, types: [.commaSeparatedText]) { m.openRoster($0) }
            }

            VStack(alignment: .leading, spacing: 2) {
                Stepper(value: $m.perStudent, in: 1...40) {
                    Text("Pages per student: **\(m.perStudent)**")
                }
                if let p = m.pageProblem {
                    Text(p).font(.caption).foregroundStyle(.orange)
                } else if m.doc != nil {
                    Text("\(m.pageCount) pages → \(m.sheetCount) students")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }

            HStack {
                Text("Name region")
                Spacer()
                Text(m.nameRect == nil ? "not set" : "set, on page \(m.namePage)")
                    .foregroundStyle(m.nameRect == nil ? Color.orange : Color.secondary)
                Button("Select…") { m.screen = .region }
                    .disabled(m.doc == nil)
            }

            HStack {
                Text("Save to")
                Spacer()
                Text(m.outDir?.lastPathComponent ?? "not chosen")
                    .foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.middle)
                    .help(m.outDir?.path ?? "")
                Button("Choose…") { m.chooseOutDir() }
            }

            if m.busy {
                ProgressView(value: m.progress)
                Text(m.status).font(.caption).foregroundStyle(.secondary)
            } else if !m.status.isEmpty {
                Text(m.status).font(.caption).foregroundStyle(.secondary)
            }

            HStack {
                if !m.sheets.isEmpty && !m.busy {
                    Button("Review") { m.screen = .review }
                }
                Button {
                    m.run { m.screen = .review }
                } label: {
                    Text("Read names").frame(maxWidth: .infinity)
                }
                .keyboardShortcut(.defaultAction)
                .disabled(!m.ready || m.busy)
            }
            .controlSize(.large)
        }
        .padding(16)
        .frame(width: 380)
    }
}

struct RegionView: View {
    @EnvironmentObject var m: Model
    @State private var sheet = 0
    @State private var image: NSImage?
    @State private var dragging: CGRect?
    @State private var preview = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Drag a box around where students write their name. Leave some room — handwriting wanders.")
                .font(.callout).foregroundStyle(.secondary)
            HStack(spacing: 16) {
                Picker("Name is on page", selection: $m.namePage) {
                    ForEach(1...max(1, m.perStudent), id: \.self) { Text("\($0)").tag($0) }
                }
                .fixedSize()
                Stepper("Student \(sheet + 1) of \(max(1, m.sheetCount))",
                        value: $sheet, in: 0...max(0, m.sheetCount - 1))
                Spacer()
            }
            Group {
                if let img = image {
                    Image(nsImage: img)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .overlay(GeometryReader { g in canvas(g.size) })
                        .border(Color.secondary.opacity(0.4))
                } else {
                    Color.secondary.opacity(0.08)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            HStack {
                Text(preview).font(.callout).lineLimit(1)
                Spacer()
                Button("Done") { m.screen = .setup }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(14)
        .frame(minWidth: 560, idealWidth: 640, minHeight: 720, idealHeight: 820)
        .onAppear(perform: reload)
        .onChange(of: sheet) { reload() }
        .onChange(of: m.namePage) { reload() }
        .onChange(of: m.scanURL) { sheet = 0; reload() }
    }

    func canvas(_ size: CGSize) -> some View {
        ZStack(alignment: .topLeading) {
            Color.clear.contentShape(Rectangle())
            if let r = dragging ?? m.nameRect {
                Rectangle()
                    .fill(Color.accentColor.opacity(0.15))
                    .overlay(Rectangle().stroke(Color.accentColor, lineWidth: 2))
                    .frame(width: r.width * size.width, height: r.height * size.height)
                    .offset(x: r.minX * size.width, y: r.minY * size.height)
                    .allowsHitTesting(false)
            }
        }
        .gesture(DragGesture(minimumDistance: 3)
            .onChanged { dragging = unit($0.startLocation, $0.location, size) }
            .onEnded { v in
                let r = unit(v.startLocation, v.location, size)
                dragging = nil
                if r.width > 0.01 && r.height > 0.005 {
                    m.nameRect = r
                    readPreview()
                }
            })
    }

    func unit(_ a: CGPoint, _ b: CGPoint, _ size: CGSize) -> CGRect {
        func c(_ v: CGFloat) -> CGFloat { min(1, max(0, v)) }
        let x0 = c(min(a.x, b.x) / size.width), x1 = c(max(a.x, b.x) / size.width)
        let y0 = c(min(a.y, b.y) / size.height), y1 = c(max(a.y, b.y) / size.height)
        return CGRect(x: x0, y: y0, width: x1 - x0, height: y1 - y0)
    }

    var page: PDFPage? {
        guard let d = m.doc, m.namePage <= m.perStudent else { return nil }
        return d.page(at: min(d.pageCount - 1, sheet * m.perStudent + m.namePage - 1))
    }

    func reload() {
        guard let p = page, let cg = render(p, dpi: 144) else { image = nil; return }
        let s = displaySize(p)
        image = NSImage(cgImage: cg, size: s)
        readPreview()
    }

    /// Read this student's box now, so a badly placed region shows up before the run.
    func readPreview() {
        guard let p = page, let r = m.nameRect else { preview = ""; return }
        preview = "Reading…"
        let roster = m.roster
        guard let crop = render(p, r, dpi: ocrDPI) else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let reads = recognize(crop, words: customWords(roster))
            var text = reads.first.map { "Reads “\($0)”" } ?? "Nothing readable in the box"
            if !reads.isEmpty, let best = roster.max(by: { score(reads, $0) < score(reads, $1) }) {
                text += String(format: "  →  %@ (%.2f)", best.display, score(reads, best))
            }
            DispatchQueue.main.async { preview = text }
        }
    }
}

struct SheetRow: View {
    @EnvironmentObject var m: Model
    @Binding var sheet: Sheet
    let duplicate: Bool

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("#\(sheet.id + 1)").font(.headline.monospacedDigit())
                Text("p. \(sheet.pages.first! + 1)–\(sheet.pages.last! + 1)")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .frame(width: 58, alignment: .leading)

            Group {
                if let c = sheet.crop {
                    Image(decorative: c, scale: 1)
                        .resizable()
                        .interpolation(.high)
                        .aspectRatio(contentMode: .fit)
                } else {
                    Color.clear
                }
            }
            .frame(width: 280, height: 56)
            .background(Color.white)
            .border(Color.secondary.opacity(0.3))

            VStack(alignment: .leading, spacing: 4) {
                Picker("", selection: $sheet.choice) {
                    Text("Unmatched").tag(-1)
                    Divider()
                    ForEach(m.roster) { Text($0.display).tag($0.id) }
                }
                .labelsHidden()
                .frame(width: 220)
                Text(sheet.readings.first.map { "read “\($0)”" } ?? "nothing read")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }

            Spacer(minLength: 8)
            badge
        }
        .padding(.vertical, 3)
    }

    @ViewBuilder var badge: some View {
        if duplicate {
            Label("Two sheets", systemImage: "xmark.octagon.fill").foregroundStyle(.red)
        } else if sheet.choice != sheet.auto {
            Label("Changed", systemImage: "pencil.circle.fill").foregroundStyle(.blue)
        } else if !sheet.flags.isEmpty {
            VStack(alignment: .trailing, spacing: 2) {
                Label("Check", systemImage: "exclamationmark.triangle.fill")
                Text(sheet.flags.joined(separator: "; ")).font(.caption).lineLimit(2)
                    .multilineTextAlignment(.trailing)
            }
            .foregroundStyle(.orange)
            .frame(maxWidth: 180, alignment: .trailing)
        } else {
            Label(String(format: "%.2f", sheet.score), systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .help("match score")
        }
    }
}

struct ReviewView: View {
    @EnvironmentObject var m: Model
    @State private var onlyFlagged = false

    var body: some View {
        let dups = m.duplicates
        let flagged = m.sheets.filter { !$0.flags.isEmpty }.count
        VStack(spacing: 0) {
            HStack(spacing: 14) {
                Button { m.screen = .setup } label: { Label("Back", systemImage: "chevron.left") }
                Text("\(m.sheets.count) sheets").font(.headline)
                if flagged > 0 {
                    Label("\(flagged) to check", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                }
                Spacer()
                Toggle("Only flagged", isOn: $onlyFlagged).toggleStyle(.checkbox)
            }
            .padding(12)
            if !m.absent.isEmpty {
                Text("No sheet for: " + m.absent.map(\.display).joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 12).padding(.bottom, 8)
                    .textSelection(.enabled)
            }
            Divider()
            List {
                ForEach($m.sheets) { $s in
                    let dup = s.choice >= 0 && dups.contains(s.choice)
                    if !onlyFlagged || !s.flags.isEmpty || dup || s.choice != s.auto {
                        SheetRow(sheet: $s, duplicate: dup)
                    }
                }
            }
            Divider()
            HStack {
                if !dups.isEmpty {
                    Text("Two sheets can't go to the same student.").foregroundStyle(.red)
                } else {
                    Text(m.status).foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                if !m.saved.isEmpty {
                    Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting(m.saved) }
                }
                Button(m.outDir == nil ? "Choose folder…" : "Change folder…") { m.chooseOutDir() }
                Button("Save \(m.sheets.count) PDFs") { m.save() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(!dups.isEmpty || m.outDir == nil || m.sheets.isEmpty)
                    .help(m.outDir?.path ?? "")
            }
            .padding(12)
        }
        .frame(minWidth: 780, minHeight: 560)
    }
}

// MARK: - Entry

final class AppDelegate: NSObject, NSApplicationDelegate {
    var model: Model?

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    /// Files dropped on the Dock icon, or `open -a scansplit bulk.pdf roster.csv`.
    func application(_ application: NSApplication, open urls: [URL]) {
        for u in urls {
            switch u.pathExtension.lowercased() {
            case "pdf": model?.openScan(u)
            case "csv": model?.openRoster(u)
            default: break
            }
        }
    }
}

/// One window: the small setup panel, which grows into the page for choosing the
/// name region and into the review list, and shrinks back again.
struct RootView: View {
    @EnvironmentObject var m: Model

    var body: some View {
        switch m.screen {
        case .setup: MainView()
        case .region: RegionView().navigationTitle("scansplit — Name region")
        case .review: ReviewView().navigationTitle("scansplit — Review")
        }
    }
}

struct ScanSplitApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = Model()

    var body: some Scene {
        Window("scansplit", id: "main") {
            RootView().environmentObject(model)
                .onAppear { delegate.model = model }
        }
        .windowResizability(.contentSize)
    }
}

@main
enum Entry {
    static func main() {
        let args = Array(CommandLine.arguments.dropFirst())
        if args.contains("--scan") || args.contains("--help") {
            exit(runCLI(args))
        }
        ScanSplitApp.main()
    }
}
