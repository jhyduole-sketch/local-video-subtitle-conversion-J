import AppKit
import Foundation
import Vision


func recognizeImage(at path: String, languages: [String]) throws -> [[String: Any]] {
    guard let image = NSImage(contentsOfFile: path) else {
        return []
    }
    var proposedRect = NSRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(
        forProposedRect: &proposedRect,
        context: nil,
        hints: nil
    ) else {
        return []
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = languages

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    try handler.perform([request])

    return (request.results ?? []).compactMap { observation in
        guard let candidate = observation.topCandidates(1).first else {
            return nil
        }
        let box = observation.boundingBox
        return [
            "text": candidate.string,
            "confidence": candidate.confidence,
            "x": box.origin.x,
            "y": box.origin.y,
            "width": box.size.width,
            "height": box.size.height,
        ]
    }
}


guard CommandLine.arguments.count >= 2 else {
    fputs("Usage: vision-ocr FRAME_DIR [LANGUAGE_1,LANGUAGE_2]\n", stderr)
    exit(2)
}

let frameDirectory = CommandLine.arguments[1]
let languages = CommandLine.arguments.count >= 3
    ? CommandLine.arguments[2].split(separator: ",").map(String.init)
    : ["ja-JP", "zh-Hans", "zh-Hant", "en-US"]

do {
    let names = try FileManager.default.contentsOfDirectory(atPath: frameDirectory)
        .filter { $0.hasPrefix("frame-") && $0.hasSuffix(".jpg") }
        .sorted()

    for (offset, name) in names.enumerated() {
        let path = (frameDirectory as NSString).appendingPathComponent(name)
        let observations = try autoreleasepool {
            try recognizeImage(at: path, languages: languages)
        }
        let payload: [String: Any] = [
            "frameIndex": offset + 1,
            "observations": observations,
        ]
        let data = try JSONSerialization.data(withJSONObject: payload)
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([0x0A]))
    }
} catch {
    fputs("Vision OCR failed: \(error)\n", stderr)
    exit(1)
}
