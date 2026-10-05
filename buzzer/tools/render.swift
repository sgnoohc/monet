// Renders every tossup in packets.json to <packet>-NN.wav with the macOS speech engine.
// usage: swift render.swift packets.json outdir [voice name]
import AVFoundation
import Foundation

let args = CommandLine.arguments
let packets = try! JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: args[1]))) as! [String: [[String]]]
let outDir = URL(fileURLWithPath: args[2])
let wanted = args.count > 3 ? args[3] : "Samantha"

let voices = AVSpeechSynthesisVoice.speechVoices().filter { $0.name == wanted && $0.language.hasPrefix("en") }
guard let voice = voices.max(by: { $0.quality.rawValue < $1.quality.rawValue }) else { fatalError("voice not found") }
print("voice: \(voice.name) (\(voice.identifier))")

let synth = AVSpeechSynthesizer()
for packet in packets.keys.sorted() {
  for (i, qa) in packets[packet]!.enumerated() {
    let name = String(format: "%@-%02d", packet, i + 1)
    let u = AVSpeechUtterance(string: qa[0])
    u.voice = voice
    var finished = false
    var file: AVAudioFile? = nil
    var frames = 0
    synth.write(u) { buf in
      guard let pcm = buf as? AVAudioPCMBuffer else { return }
      if pcm.frameLength == 0 { finished = true; return }
      if file == nil {
        file = try! AVAudioFile(forWriting: outDir.appendingPathComponent(name + ".wav"), settings: pcm.format.settings,
                                commonFormat: pcm.format.commonFormat, interleaved: pcm.format.isInterleaved)
      }
      try! file!.write(from: pcm)
      frames += Int(pcm.frameLength)
    }
    // the write callbacks arrive on the main run loop, so spin it instead of blocking
    while !finished { RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.02)) }
    file = nil
    print("\(name): \(frames) frames")
  }
}
