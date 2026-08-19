#!/usr/bin/env swift

import Darwin
import Foundation

enum ICNSError: Error, LocalizedError {
    case usage
    case invalidPNG(String)
    case outputTooLarge

    var errorDescription: String? {
        switch self {
        case .usage:
            return "usage: make-icns.swift ICONSET_DIRECTORY OUTPUT.icns"
        case let .invalidPNG(name):
            return "missing or invalid PNG in iconset: \(name)"
        case .outputTooLarge:
            return "ICNS output exceeds the 32-bit container limit"
        }
    }
}

func bigEndianData(_ value: UInt32) -> Data {
    var encoded = value.bigEndian
    return withUnsafeBytes(of: &encoded) { Data($0) }
}

func buildICNS(iconset: URL, output: URL) throws {
    // Modern ICNS PNG chunks. Scale-specific aliases are included so Finder
    // can choose the correct representation on both Retina and non-Retina
    // displays without depending on legacy raw bitmap/mask chunks.
    let chunks: [(type: String, filename: String)] = [
        ("icp4", "icon_16x16.png"),
        ("icp5", "icon_32x32.png"),
        ("icp6", "icon_32x32@2x.png"),
        ("ic07", "icon_128x128.png"),
        ("ic08", "icon_256x256.png"),
        ("ic09", "icon_512x512.png"),
        ("ic10", "icon_512x512@2x.png"),
        ("ic11", "icon_16x16@2x.png"),
        ("ic12", "icon_32x32@2x.png"),
        ("ic13", "icon_128x128@2x.png"),
        ("ic14", "icon_256x256@2x.png"),
    ]

    let pngSignature = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
    var encodedChunks = Data()
    for chunk in chunks {
        let file = iconset.appendingPathComponent(chunk.filename)
        let image = try Data(contentsOf: file, options: .mappedIfSafe)
        guard image.starts(with: pngSignature),
              let type = chunk.type.data(using: .ascii),
              type.count == 4,
              image.count <= Int(UInt32.max) - 8
        else {
            throw ICNSError.invalidPNG(chunk.filename)
        }
        encodedChunks.append(type)
        encodedChunks.append(bigEndianData(UInt32(image.count + 8)))
        encodedChunks.append(image)
    }

    guard encodedChunks.count <= Int(UInt32.max) - 8 else {
        throw ICNSError.outputTooLarge
    }
    var container = Data("icns".utf8)
    container.append(bigEndianData(UInt32(encodedChunks.count + 8)))
    container.append(encodedChunks)
    try container.write(to: output, options: .atomic)
}

do {
    guard CommandLine.arguments.count == 3 else { throw ICNSError.usage }
    try buildICNS(
        iconset: URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true),
        output: URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: false)
    )
} catch {
    FileHandle.standardError.write(Data("make-icns: \(error.localizedDescription)\n".utf8))
    exit(1)
}
