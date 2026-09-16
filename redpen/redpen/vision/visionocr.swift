// On-device handwriting/text recognition through Apple's Vision framework.
// usage: visionocr <image.png> [customWords.txt]
// prints "text<TAB>confidence", best candidates first.  Nothing is networked.
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count > 1,
      let img = NSImage(contentsOfFile: args[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("cannot read image\n".data(using: .utf8)!)
    exit(1)
}
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false          // proper names are not dictionary words
req.recognitionLanguages = ["en-US"]
if args.count > 2, let w = try? String(contentsOfFile: args[2], encoding: .utf8) {
    req.customWords = w.split(separator: "\n").map(String.init).filter { !$0.isEmpty }
}
try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
for obs in (req.results ?? []) {
    for cand in obs.topCandidates(3) {
        print("\(cand.string)\t\(String(format: "%.3f", cand.confidence))")
    }
}
