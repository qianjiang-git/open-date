import Foundation

/// One line in the user's OWN words: their side of a recorded conversation (other people's lines are never stored),
/// something they typed, or a "how I'd say it" fix from the Is-this-you quiz (`locked`, always kept).
public struct OwnLine: Codable, Sendable, Equatable {
    public var text: String
    public var t: Double
    public var locked: Bool
    public init(_ text: String, t: Double = Date().timeIntervalSince1970, locked: Bool = false) {
        self.text = text; self.t = t; self.locked = locked
    }
}

/// Sentence shape, measured without any model.
public struct StyleTraits: Codable, Sendable, Equatable {
    public var lines = 0
    public var avgWords = 0.0
    public var questionRate = 0.0
    public var exclaimRate = 0.0
    public var emojiRate = 0.0
    public var lowercaseStart = 0.0
    public var laughRate = 0.0
}

/// How you talk, learned from your own lines on the device: example bank, sentence shape, pet phrases.
public enum Style {
    public static let maxBank = 400
    static let stop: Set<String> = Set(("i you the a an to and of it is in that my me for on with be was so just like it's i'm im do not but "
        + "this have are at what we they he she if or as can get got go").split(separator: " ").map(String.init))

    static func words(_ s: String) -> [String] {
        var out: [String] = []
        var cur = ""
        for ch in s {
            if ch.isLetter && ch.isASCII || ch == "'" { cur.append(ch) }
            else {
                if !cur.isEmpty { out.append(cur); cur = "" }
                if ch.unicodeScalars.contains(where: { (0x4E00...0x9FFF).contains($0.value) }) { out.append(String(ch)) }
            }
        }
        if !cur.isEmpty { out.append(cur) }
        return out
    }

    /// A usable example line, or nil (too short, too long, only a link).
    public static func clean(_ raw: String) -> String? {
        var t = raw.replacingOccurrences(of: #"https?://\S+"#, with: "", options: .regularExpression)
        t = t.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression).trimmingCharacters(in: .whitespaces)
        guard words(t).count >= 3, t.count <= 280 else { return nil }
        return t
    }

    /// Locked fixes first, then the newest distinct lines.
    public static func bank(_ lines: [OwnLine]) -> [String] {
        var seen = Set<String>(), out: [String] = []
        for l in lines.sorted(by: { ($0.locked ? 0 : 1, -$0.t) < ($1.locked ? 0 : 1, -$1.t) }) {
            guard let c = clean(l.text), seen.insert(c.lowercased()).inserted else { continue }
            out.append(c)
            if out.count >= maxBank { break }
        }
        return out
    }

    public static func traits(_ lines: [OwnLine]) -> StyleTraits {
        let texts = lines.compactMap { clean($0.text) }
        guard !texts.isEmpty else { return StyleTraits() }
        let n = Double(texts.count)
        func share(_ f: (String) -> Bool) -> Double { (Double(texts.filter(f).count) / n * 100).rounded() / 100 }
        return StyleTraits(
            lines: texts.count,
            avgWords: (Double(texts.map { words($0).count }.reduce(0, +)) / n * 10).rounded() / 10,
            questionRate: share { $0.contains("?") || $0.contains("？") },
            exclaimRate: share { $0.contains("!") },
            emojiRate: share { $0.unicodeScalars.contains { $0.properties.isEmojiPresentation } },
            lowercaseStart: share { $0.first?.isLowercase == true },
            laughRate: share { $0.range(of: #"\b(haha+|lol|lmao|hehe)\b|哈哈"#, options: [.regularExpression, .caseInsensitive]) != nil })
    }

    /// Pet phrases: 2-3 word sequences repeated at least twice, not made only of filler words.
    public static func phrases(_ lines: [OwnLine], limit: Int = 8) -> [String] {
        var count: [String: Int] = [:], order: [String] = []
        for l in lines {
            let w = words(clean(l.text) ?? "").map { $0.lowercased() }
            for n in 2...3 where w.count >= n {
                for i in 0...(w.count - n) {
                    let g = Array(w[i..<(i + n)])
                    if g.allSatisfy({ stop.contains($0) }) { continue }
                    let k = g.joined(separator: " ")
                    if count[k] == nil { order.append(k) }
                    count[k, default: 0] += 1
                }
            }
        }
        return order.filter { count[$0]! >= 2 }.sorted { count[$0]! > count[$1]! }.prefix(limit).map { $0 }
    }

    /// The k examples sharing the most content words with `query`: few-shot voice for one message.
    public static func retrieve(_ k: Int, for query: String, in examples: [String]) -> [String] {
        let q = Set(words(query).map { $0.lowercased() }.filter { !stop.contains($0) })
        return examples.enumerated()
            .map { (i, e) in (i, e, q.intersection(words(e).map { $0.lowercased() }).count) }
            .sorted { ($0.2, -$0.0) > ($1.2, -$1.0) }
            .prefix(k).map { $0.1 }
    }
}
