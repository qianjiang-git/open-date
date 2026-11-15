import Foundation

/// One turn of a recorded conversation. Only the user's turns (`me`) are ever kept as data; the other people's turns are
/// read in memory, on the device, to measure the exchange (did you ask back, build on what they said) and then dropped.
public struct Turn: Codable, Sendable {
    public var me: Bool
    public var text: String
    public init(me: Bool, _ text: String) { self.me = me; self.text = text }
}

/// How you behave IN a conversation, measured without any model.
public struct ConversationHabits: Codable, Sendable, Equatable {
    public var myTurns = 0
    public var talkShare = 0.0          // 0.5 = balanced
    public var avgTurnWords = 0.0
    public var questionRate = 0.0
    public var followUpShare = 0.0      // questions that build on what the other person just said
    public var selfDisclosureRate = 0.0
    public var reciprocity: Double?     // after they open up, how often you open up back
    public var laughRate = 0.0

    public var description: String {
        guard myTurns > 0 else { return "Not enough recorded conversation yet." }
        let talk = talkShare > 0.6 ? "Talks a lot" : talkShare < 0.4 ? "Lets others talk more" : "Keeps the talk balanced"
        let q = questionRate > 0.3 && followUpShare > 0.5 ? "asks lots of follow-up questions about the other person"
            : questionRate > 0.3 ? "asks questions" : "rarely asks questions back"
        let open = selfDisclosureRate > 0.15 ? "opens up readily" : "keeps personal things private at first"
        return "\(talk), \(q), \(open); about \(Int(avgTurnWords.rounded())) words per message."
    }
}

public enum Dynamics {
    static let selfDisclosure = #"\b(i feel|i felt|i'm (scared|nervous|excited|sad|happy|worried)|honestly|to be honest|my (mom|dad|family|ex)|i've never told|i struggle|i love|i hate|i wish)\b|我觉得|说实话|我其实"#
    static let laugh = #"\b(haha+|lol|lmao|hehe)\b|\[laugh(ter|s)?\]|哈哈"#

    static func has(_ s: String, _ rx: String) -> Bool { s.range(of: rx, options: [.regularExpression, .caseInsensitive]) != nil }
    static func content(_ s: String) -> Set<String> {
        Set(Style.words(s).map { $0.lowercased() }.filter { $0.count > 2 && !Style.stop.contains($0) })
    }

    /// nil when there is too little of the user (under 20 turns) to say anything.
    public static func measure(_ transcripts: [[Turn]]) -> ConversationHabits? {
        var mine = 0, totalWords = 0, myWords = 0, asked = 0, followUps = 0, disclosed = 0, laughs = 0
        var recip: [Double] = []
        for tr in transcripts {
            var prevOther: String?
            var theyOpenedUp = false
            for turn in tr {
                let w = Style.words(turn.text).count
                totalWords += w
                guard turn.me else { prevOther = turn.text; theyOpenedUp = has(turn.text, selfDisclosure); continue }
                mine += 1; myWords += w
                if turn.text.contains("?") || turn.text.contains("？") {
                    asked += 1
                    if let p = prevOther, !content(p).intersection(content(turn.text)).isEmpty { followUps += 1 }
                }
                if has(turn.text, selfDisclosure) { disclosed += 1 }
                if has(turn.text, laugh) { laughs += 1 }
                if theyOpenedUp { recip.append(has(turn.text, selfDisclosure) ? 1 : 0); theyOpenedUp = false }
            }
        }
        guard mine >= 20 else { return nil }
        func r(_ x: Double) -> Double { (x * 100).rounded() / 100 }
        return ConversationHabits(
            myTurns: mine, talkShare: r(Double(myWords) / Double(max(1, totalWords))),
            avgTurnWords: (Double(myWords) / Double(mine) * 10).rounded() / 10,
            questionRate: r(Double(asked) / Double(mine)),
            followUpShare: asked > 0 ? r(Double(followUps) / Double(asked)) : 0,
            selfDisclosureRate: r(Double(disclosed) / Double(mine)),
            reciprocity: recip.isEmpty ? nil : r(recip.reduce(0, +) / Double(recip.count)),
            laughRate: r(Double(laughs) / Double(mine)))
    }
}
