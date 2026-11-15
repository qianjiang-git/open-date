import Foundation
import SecondYouKit

// Runs two people's training and a full match on THIS machine's on-device model (no network calls at all).
// On an iPhone the two sides run on two phones and only the chat messages cross between them.
let mayaLines = ["haha okay that's actually so true", "I've been obsessed with climbing lately, my forearms hate me", "honestly I need a weekend with zero plans",
    "wait you've never had Burmese food?? we have to fix that", "I love when people send voice notes instead of texts tbh", "I'm staying in SF though, this city has my heart",
    "can we talk about how good that documentary was", "I'm such a morning person it's embarrassing", "okay but pineapple on pizza is valid and I will die on this hill",
    "work has been a lot but I love my team", "haha you're ridiculous", "I want a big family someday, like loud dinners and chaos",
    "do you ever just walk around a new neighborhood with no plan?", "that's the nicest thing anyone's said to me this week"]
let benLines = ["lol fair", "I teach high school chemistry so I've heard every excuse", "do you climb outdoors or gym only?", "I make a mean dumpling",
    "honestly I'm pretty low-key, a good bookstore and coffee and I'm happy", "wait what's your favorite trail in Marin?", "haha okay you win that one",
    "I've never been to Burma Superstar, is it worth the line?", "kids are the best and the worst, that's why I want three", "I'm a bit of a planner ngl",
    "what got you into climbing?", "I don't really drink, maybe a beer at a game", "I'll defend the oxford comma forever", "how was your week actually?"]

print("On-device model:", OnDevice.status)
let maya = await Trainer.train(name: "Maya", lines: mayaLines.map { OwnLine($0) },
    questionnaire: [.kids: Answer("yes", matters: 3), .location: Answer("staying here", matters: 2), .lookingFor: Answer("long-term", matters: 3),
                    .smoking: Answer("no", matters: 2), .drinking: Answer("socially")], consent: .init(traits: true))
let ben = await Trainer.train(name: "Ben", lines: benLines.map { OwnLine($0) },
    questionnaire: [.kids: Answer("yes", matters: 2), .location: Answer("staying here"), .lookingFor: Answer("long-term", matters: 2),
                    .smoking: Answer("no", matters: 3), .drinking: Answer("no")], consent: .init(traits: true))
print("Maya dealbreakers:", maya.dealbreakers.map(\.rawValue), "traits:", maya.traits.map { "\($0.humor); \($0.topics)" } ?? "none (model unavailable)")
print("Ben dealbreakers:", ben.dealbreakers.map(\.rawValue), "traits:", ben.traits.map { "\($0.humor); \($0.topics)" } ?? "none (model unavailable)")

guard OnDevice.status == "available" else { print("Skipping the match: needs Apple Intelligence on this device."); exit(0) }
let (pa, pb) = Loopback.pair()
let a = AgentSide(profile: maya, transport: pa), b = AgentSide(profile: ben, transport: pb)
async let ra = a.evaluate(goesFirst: true, peerName: "Ben")
async let rb = b.evaluate(goesFirst: false, peerName: "Maya")
do {
    let (x, _) = try await (ra, rb)
    for s in x.scenarios {
        print("\n== \(s.scenario.rawValue)  (Maya's phone judged: chemistry \(Int(s.myVerdict.chemistry * 10))/10, clash \(s.myVerdict.clash))")
        for l in s.lines { print("  \(l.speaker): \(l.text)") }
        if !s.invented.isEmpty { print("  ! Maya's agent invented:", s.invented) }
    }
    print(String(format: "\nscore %.2f  interval %.2f-%.2f  match %@  clash %@", x.score, x.interval.0, x.interval.1, x.match ? "yes" : "no", x.clash ? "yes" : "no"))
} catch { print("match failed:", error) }
