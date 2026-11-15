import Foundation

/// Is this you? Before an agent may date on your behalf it has to answer dating situations the way YOU do. Below
/// `minimum` it stays out of the matching pool: matching two inaccurate stand-ins says nothing about the two people.
public enum Fidelity {
    public static let minimum = 0.7
    public static let situations: [(String, [String])] = [
        ("They cancel your first date an hour before.", ["Reschedule right away", "Say it's fine, then wait for them to reach out", "Feel put off and probably move on", "Joke about it and ask for a new day"]),
        ("On the second date they say they never want kids.", ["Fine either way", "Want to talk it through before deciding", "End it kindly - it's a dealbreaker", "Avoid the topic for now"]),
        ("They tease your favorite movie.", ["Tease back", "Defend it seriously", "Laugh it off", "Feel a bit hurt"]),
        ("They text a long message about a hard week.", ["Reply with something long and caring", "Ask what would help", "Send something light to cheer them up", "Suggest talking on the phone"]),
        ("After a great first date, how soon do you want the second?", ["Within a few days", "Within a week or two", "Whenever it happens", "Only if they ask"]),
        ("Plans for a first date:", ["A walk or coffee", "Dinner and drinks", "Something active", "A show or event"]),
    ]

    public struct Result: Sendable {
        public var score: Double
        public var passed: Bool
        public var misses: [(situation: String, agent: String, you: String)]
    }

    /// `userAnswers`: the user's own pick (0-3) per situation, collected once in the app.
    public static func check(_ p: DatingProfile, userAnswers: [Int]) async throws -> Result {
        let text = situations.enumerated().map { i, s in
            "\(i + 1). \(s.0) Options: " + s.1.enumerated().map { "\($0)=\($1)" }.joined(separator: " | ")
        }.joined(separator: "\n")
        let agent = try await OnDevice.pick(card: p.card(), situations: text)
        var hits = 0, n = 0, misses: [(String, String, String)] = []
        for (i, u) in userAnswers.enumerated() where i < situations.count {
            n += 1
            let a = i < agent.count ? agent[i] : -1
            if a == u { hits += 1 } else {
                misses.append((situations[i].0, (0..<4).contains(a) ? situations[i].1[a] : "-", situations[i].1[u]))
            }
        }
        let s = n > 0 ? Double(hits) / Double(n) : 0
        return Result(score: (s * 100).rounded() / 100, passed: s >= minimum, misses: misses)
    }
}
