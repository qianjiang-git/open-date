import Foundation

/// The onboarding questionnaire. Values and dealbreakers are ASKED, never inferred: guessing kids, faith or moving from
/// recordings is unreliable and invasive. Faith, orientation, health and the like are only ever what the user typed.
public enum Question: String, Codable, Sendable, CaseIterable {
    case kids, location, faith, drinking, smoking, ambition, pace, lookingFor

    public var prompt: String {
        switch self {
        case .kids: "Do you want kids someday?"
        case .location: "Where do you see yourself in a few years?"
        case .faith: "Faith in your life?"
        case .drinking: "Drinking?"
        case .smoking: "Smoking?"
        case .ambition: "Work in your life right now?"
        case .pace: "When dating, you like to move..."
        case .lookingFor: "Looking for..."
        }
    }
    public var options: [String] {
        switch self {
        case .kids: ["yes", "no", "open"]
        case .location: ["staying here", "likely moving", "open"]
        case .faith: ["none", "spiritual", "practicing"]
        case .drinking: ["no", "socially", "often"]
        case .smoking: ["no", "yes"]
        case .ambition: ["chill", "balanced", "driven"]
        case .pace: ["slow", "medium", "fast"]
        case .lookingFor: ["long-term", "open to see", "casual"]
        }
    }
    /// Answered "matters 3" on one of these, it becomes a dealbreaker the agent must hold.
    public var dealbreakerRule: String? {
        switch self {
        case .kids: "must match on kids"
        case .location: "must match on where to live"
        case .faith: "must share faith"
        case .drinking: "won't date someone who drinks often"
        case .smoking: "won't date a smoker"
        case .lookingFor: "must want the same kind of relationship"
        default: nil
        }
    }
}

public struct Answer: Codable, Sendable, Equatable {
    public var answer: String
    public var matters: Int            // 0 = doesn't matter ... 3 = dealbreaker
    public init(_ answer: String, matters: Int = 1) { self.answer = answer; self.matters = max(0, min(3, matters)) }
}

/// Read by the on-device model from the user's own lines, only with consent.
public struct TraitsReading: Codable, Sendable, Equatable {
    public var humor: String
    public var humorExamples: [String]
    public var conflict: String
    public var topics: [String]
    public var energy: String
    public init(humor: String, humorExamples: [String], conflict: String, topics: [String], energy: String) {
        self.humor = humor; self.humorExamples = humorExamples; self.conflict = conflict; self.topics = topics; self.energy = energy
    }
}

/// Learned from what the user does: matches accepted or skipped, how dates went.
public struct Revealed: Codable, Sendable, Equatable {
    public var accepted = 0
    public var skipped = 0
    public var likedHumor: [String: Int] = [:]
    public var dateRatings: [Double] = []
}

/// Everything Second You learned. Lives only in the device's encrypted vault (Vault.swift); only `card()` text ever
/// reaches the on-device model, and nothing in here is ever sent to another device or a server.
public struct DatingProfile: Codable, Sendable {
    public var name: String
    public var version = 0
    public var trainedAt = 0.0
    public var values: [Question: Answer] = [:]
    public var faithName: String?
    public var style = StyleTraits()
    public var phrases: [String] = []
    public var examples: [String] = []
    public var habits: ConversationHabits?
    public var traits: TraitsReading?
    public var revealed = Revealed()
    public var fidelity: Double?

    public init(name: String) { self.name = name }

    public var dealbreakers: [Question] {
        Question.allCases.filter { values[$0].map { $0.matters >= 3 } == true && $0.dealbreakerRule != nil }
    }

    /// What this person's agent is told, and nothing more. Every claim the agent makes must come from here.
    public func card() -> String {
        var life = Question.allCases.compactMap { q -> String? in
            guard let a = values[q] else { return nil }
            return "\(q.rawValue): \(a.answer)\(a.matters >= 3 ? " (very important)" : "")"
        }.joined(separator: "; ")
        if life.isEmpty { life = "not shared yet" }
        if let f = faithName, !f.isEmpty { life += "; faith: \(f)" }
        var out = [
            "You are \(name)'s Second You: you speak AS \(name), in first person, on a dating app.",
            "Life and values (from \(name)'s own answers): \(life).",
            "Dealbreakers you never give up to be nice: \(dealbreakers.compactMap(\.dealbreakerRule).joined(separator: ", ").ifEmpty("none")).",
        ]
        if let t = traits {
            if !t.topics.isEmpty { out.append("Into: \(t.topics.joined(separator: ", ")).") }
            out.append("Humor: \(t.humor)\(t.humorExamples.first.map { " (e.g. \"\($0)\")" } ?? "").")
            if t.conflict != "unknown" { out.append("When you disagree you \(t.conflict).") }
        }
        if let h = habits { out.append("In conversation: \(h.description)") }
        if style.lines > 0 {
            out.append("Message shape: about \(Int(style.avgWords.rounded())) words, questions in \(Int(style.questionRate * 100))% of messages.")
        }
        if !examples.isEmpty { out.append("How \(name) actually writes (match this voice):\n- " + examples.prefix(6).joined(separator: "\n- ")) }
        if !phrases.isEmpty { out.append("Pet phrases: \(phrases.joined(separator: ", ")).") }
        out.append("RULES: Only state facts and preferences written above. If asked about something not above, say you'd rather talk "
            + "about it in person - never invent a preference to agree with them. Never share contact details, workplace, address "
            + "or photos. Never mention being an AI.")
        return out.joined(separator: "\n")
    }
}

extension String {
    func ifEmpty(_ s: String) -> String { isEmpty ? s : self }
}
