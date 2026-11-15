import Foundation

/// The only place Second You keeps data: one JSON file in Application Support/SecondYou, written with
/// `.completeFileProtection` (encrypted, unreadable while the iPhone is locked) and excluded from iCloud / device backups.
/// There is no upload path anywhere in this package.
public enum Vault {
    public static let directory: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("SecondYou", isDirectory: true)
    }()
    static var file: URL { directory.appendingPathComponent("profile.json") }

    public static func save(_ p: DatingProfile) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var dir = directory
        var rv = URLResourceValues(); rv.isExcludedFromBackup = true
        try? dir.setResourceValues(rv)
        let data = try JSONEncoder().encode(p)
        #if os(iOS)
        try data.write(to: file, options: [.atomic, .completeFileProtection])
        #else
        try data.write(to: file, options: [.atomic])
        #endif
    }

    public static func load() -> DatingProfile? {
        guard let d = try? Data(contentsOf: file) else { return nil }
        return try? JSONDecoder().decode(DatingProfile.self, from: d)
    }

    /// "Delete Second You": the profile, the example bank and every learned trait, at once.
    public static func wipe() { try? FileManager.default.removeItem(at: directory) }
}
