import Foundation

/// Narrow policy for the Workbench's user-requested canvas screenshot. It
/// deliberately accepts no network URL, arbitrary MIME type, or automatic
/// destination; the native shell still presents NSSavePanel before writing.
public enum ScreenshotDownloadPolicy {
    public static let maximumEncodedDataURLBytes = 24 * 1_024 * 1_024
    public static let maximumDecodedPNGBytes: Int64 = 18 * 1_024 * 1_024

    public static func allowsNavigation(url: URL?, shouldPerformDownload: Bool) -> Bool {
        guard shouldPerformDownload,
              let url,
              url.scheme?.lowercased() == "data"
        else {
            return false
        }
        let value = url.absoluteString
        let prefix = "data:image/png;base64,"
        guard value.utf8.count <= maximumEncodedDataURLBytes,
              value.prefix(prefix.count).lowercased() == prefix
        else {
            return false
        }
        return true
    }

    public static func allowsResponse(mimeType: String?, expectedContentLength: Int64) -> Bool {
        guard mimeType?.lowercased() == "image/png" else { return false }
        return expectedContentLength < 0 || expectedContentLength <= maximumDecodedPNGBytes
    }

    public static func safeFilename(_ suggestedFilename: String) -> String {
        let component = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        let stem = (component as NSString).deletingPathExtension
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-_"))
        let normalizedScalars = stem.unicodeScalars.map { scalar -> Character in
            allowed.contains(scalar) ? Character(String(scalar)) : "-"
        }
        let normalized = String(normalizedScalars)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-_"))
        let bounded = String(normalized.prefix(80))
        return "\(bounded.isEmpty ? "M5Stack-Simulator" : bounded).png"
    }
}
