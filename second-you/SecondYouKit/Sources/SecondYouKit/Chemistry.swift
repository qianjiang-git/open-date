import Foundation

/// Two Second Yous meet before their people do. Each phone runs ITS OWN agent on its own on-device model; the only
/// thing that crosses between the phones is the chat messages themselves (and each side's final verdict numbers).
/// Profiles, example banks and cards never leave their phone.
///
/// Validated in the simulation (sim/dating_sim.py, virtual people only): judge score vs true compatibility Spearman 0.73,
/// 41/43 dealbreakers caught, agents rating themselves 0.22. Two failures found there are fixed here:
///  1. the future talk ended before every dealbreaker came up -> it continues until each of MY dealbreaker topics has
///     been raised (each phone enforces its own), up to `maxFutureTurns`
///  2. an agent invented a preference to be agreeable -> each phone audits ITS OWN agent against ITS OWN card; a
///     conversation with an invented claim is run again once, and the match is blocked if it happens again

/// How messages travel between the two phones (Multipeer, a relay that stores nothing, or in-process for tests).
public protocol AgentTransport: Sendable {
    func send(_ message: String) async throws
    func receive() async throws -> String
}

public enum Scenario: String, CaseIterable, Sendable {
    case firstChat, planDate, futureTalk
    public var situation: String {
        switch self {
        case .firstChat: "You just matched on a dating app and are texting for the first time. Get to know each other naturally."
        case .planDate: "You've texted for a few days. Now try to plan a first date this weekend that both of you would enjoy."
        case .futureTalk: "You're on a second date, at dinner. The talk turns to the future: kids, where you'll live, faith, drinking and smoking, what you're looking for, how fast you like to move. Be honest, the way the real person would."
        }
    }
}

public struct ScenarioResult: Sendable {
    public var scenario: Scenario
    public var lines: [(speaker: String, text: String)]
    public var myVerdict: Verdict
    public var invented: [String]
}

public struct MatchResult: Sendable {
    public var score: Double
    public var interval: (Double, Double)
    public var match: Bool
    public var clash: Bool
    public var inventedByMyAgent: [String]
    public var scenarios: [ScenarioResult]
}

public actor AgentSide {
    public let profile: DatingProfile
    let transport: AgentTransport
    public static let turns = 6
    public static let maxFutureTurns = 14
    public static let matchFloor = 0.6

    static let topicWords: [Question: String] = [
        .kids: #"\bkids?\b|children|孩子"#, .location: #"\bmov(e|ing)\b|stay(ing)? (in|here)|long[- ]distance|city"#,
        .faith: #"faith|relig|church|temple|synagogue|mosque|pray"#, .drinking: #"drink|wine|beer|sober|alcohol"#,
        .smoking: #"smok|cigar|vape"#, .lookingFor: #"long[- ]term|serious|casual|relationship|looking for"#,
    ]

    public init(profile: DatingProfile, transport: AgentTransport) { self.profile = profile; self.transport = transport }

    /// One conversation. `goesFirst` is agreed out of band (e.g. the phone that proposed the match).
    func converse(_ scenario: Scenario, goesFirst: Bool, peerName: String, hint: String = "") async throws -> [(String, String)] {
        var lines: [(String, String)] = []
        var limit = AgentSide.turns
        var i = 0
        let mine = scenario == .futureTalk ? Set(profile.dealbreakers + [.kids, .location]) : []
        while i < limit {
            let myTurn = (i % 2 == 0) == goesFirst
            let all = lines.map { $0.1 }.joined(separator: "\n")
            let missing = mine.filter { q in all.range(of: AgentSide.topicWords[q] ?? "$^", options: [.regularExpression, .caseInsensitive]) == nil }
            if scenario == .futureTalk, i == limit - 1, limit < AgentSide.maxFutureTurns {
                // both phones extend together: each says whether it still has topics to cover
                if myTurn { try await transport.send(missing.isEmpty ? "<done>" : "<more>") }
                let peerWantsMore = myTurn ? (try await transport.receive()) == "<more>" : (try await transport.receive()) == "<more>"
                if !myTurn { try await transport.send(missing.isEmpty ? "<done>" : "<more>") }
                if !missing.isEmpty || peerWantsMore { limit += 2 }
            }
            if myTurn {
                let extra = !missing.isEmpty && i >= 2 ? " Bring up honestly, if it hasn't come up: \(missing.prefix(2).map(\.rawValue).joined(separator: ", "))." : ""
                let rules = "Write ONLY \(profile.name)'s next text message (max 40 words), like a real person. Stay true to your card - do not agree just to be nice. If something hits a dealbreaker, say so kindly but clearly.\(extra) \(hint)"
                let transcript = lines.map { "\($0.0): \($0.1)" }.joined(separator: "\n").ifEmpty("(no messages yet - you write the first one)")
                let msg = try await OnDevice.agentMessage(card: profile.card(), rules: rules,
                                                          situation: scenario.situation + " You are texting with \(peerName).", transcript: transcript)
                let clean = String(msg.prefix(400))
                try await transport.send(clean)
                lines.append((profile.name, clean))
            } else {
                lines.append((peerName, String(try await transport.receive().prefix(400))))
            }
            i += 1
        }
        return lines
    }

    public func run(_ scenario: Scenario, goesFirst: Bool, peerName: String) async throws -> ScenarioResult {
        var lines = try await converse(scenario, goesFirst: goesFirst, peerName: peerName)
        var invented = try await OnDevice.audit(card: profile.card(), myMessages: lines.filter { $0.0 == profile.name }.map(\.1))
        // both phones must agree to rerun, so each tells the other whether its own agent invented something
        try await transport.send(invented.isEmpty ? "<ok>" : "<rerun>")
        let peerRerun = try await transport.receive() == "<rerun>"
        if !invented.isEmpty || peerRerun {
            let hint = invented.isEmpty ? "" : "Do not claim anything about yourself beyond your card (last time: \(invented.prefix(3).joined(separator: "; ")))."
            lines = try await converse(scenario, goesFirst: goesFirst, peerName: peerName, hint: hint)
            invented = try await OnDevice.audit(card: profile.card(), myMessages: lines.filter { $0.0 == profile.name }.map(\.1))
        }
        let verdict = try await OnDevice.judge(lines.map { "\($0.0): \($0.1)" }.joined(separator: "\n"), scenario: scenario.situation)
        return ScenarioResult(scenario: scenario, lines: lines.map { (speaker: $0.0, text: $0.1) }, myVerdict: verdict, invented: invented)
    }

    /// All three scenarios, then the two phones swap only their verdict numbers and combine them.
    public func evaluate(goesFirst: Bool, peerName: String, floor: Double = AgentSide.matchFloor) async throws -> MatchResult {
        var results: [ScenarioResult] = []
        for s in Scenario.allCases { results.append(try await run(s, goesFirst: goesFirst, peerName: peerName)) }
        let mine = results.map { 0.5 * $0.myVerdict.chemistry + 0.5 * $0.myVerdict.nextDate }
        let myClash = results.contains { $0.myVerdict.clash }
        let myInvented = results.flatMap(\.invented)
        let summary = (mine.map { String(format: "%.3f", $0) } + [myClash ? "1" : "0", myInvented.isEmpty ? "0" : "1"]).joined(separator: ",")
        try await transport.send("<verdict>" + summary)
        let peer = try await transport.receive().replacingOccurrences(of: "<verdict>", with: "").split(separator: ",").map(String.init)
        let theirs = peer.prefix(3).compactMap(Double.init)
        let clash = myClash || peer.dropFirst(3).first == "1"
        let anyInvented = !myInvented.isEmpty || peer.dropFirst(4).first == "1"
        let per = zip(mine, theirs.count == 3 ? theirs : mine).map { ($0 + $1) / 2 }
        let mean = per.reduce(0, +) / Double(per.count)
        let sd = sqrt(per.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / Double(max(1, per.count - 1)))
        let penalty = clash ? 0.35 : 1.0
        let score = mean * penalty, half = 1.96 * sd / sqrt(Double(per.count)) * penalty
        let lo = max(0, score - half), hi = min(1, score + half)
        return MatchResult(score: score, interval: (lo, hi), match: lo >= floor && !clash && !anyInvented, clash: clash,
                           inventedByMyAgent: myInvented, scenarios: results)
    }
}

/// Two in-process ends of a pipe: lets one device (or a test) run both agents. Real phones use Multipeer or a relay.
public final class Loopback: AgentTransport, @unchecked Sendable {
    private var inbox: [String] = []
    private var waiters: [CheckedContinuation<String, Never>] = []
    private let lock = NSLock()
    public weak var peer: Loopback?
    public init() {}
    public static func pair() -> (Loopback, Loopback) { let a = Loopback(), b = Loopback(); a.peer = b; b.peer = a; return (a, b) }
    public func send(_ message: String) async throws { peer?.deliver(message) }
    func deliver(_ m: String) {
        lock.lock()
        if !waiters.isEmpty { let w = waiters.removeFirst(); lock.unlock(); w.resume(returning: m); return }
        inbox.append(m); lock.unlock()
    }
    public func receive() async throws -> String {
        await withCheckedContinuation { (c: CheckedContinuation<String, Never>) in
            lock.lock()
            if !inbox.isEmpty { let m = inbox.removeFirst(); lock.unlock(); c.resume(returning: m) }
            else { waiters.append(c); lock.unlock() }
        }
    }
}
