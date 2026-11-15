import XCTest
@testable import SecondYouKit

final class SecondYouKitTests: XCTestCase {
    func testStyleTraitsAndBank() {
        let lines = ["haha okay that's so true", "wait what?? no way", "I love this so much!", "ok", "haha okay that's so true"].map { OwnLine($0) }
        XCTAssertEqual(Style.bank(lines).count, 3)                 // "ok" too short, duplicate dropped
        let t = Style.traits(lines)
        XCTAssertEqual(t.lines, 4)
        XCTAssertGreaterThan(t.laughRate, 0)
        XCTAssertGreaterThan(t.questionRate, 0)
    }

    func testDealbreakersOnlyFromAnswers() {
        var p = DatingProfile(name: "A")
        p.values = [.kids: Answer("yes", matters: 3), .ambition: Answer("driven", matters: 3), .smoking: Answer("no", matters: 1)]
        XCTAssertEqual(p.dealbreakers, [.kids])                    // ambition has no dealbreaker rule; smoking not important
        XCTAssertTrue(p.card().contains("must match on kids"))
        XCTAssertTrue(p.card().contains("never invent a preference"))
    }

    func testDynamicsNeedsEnoughTurns() {
        let few = [[Turn(me: false, "hi how are you"), Turn(me: true, "good, you?")]]
        XCTAssertNil(Dynamics.measure(few))
        var many: [Turn] = []
        for i in 0..<25 { many.append(Turn(me: false, "I feel so stressed about work \(i)")); many.append(Turn(me: true, "honestly same, what happened at work?")) }
        let h = Dynamics.measure([many])!
        XCTAssertEqual(h.myTurns, 25)
        XCTAssertGreaterThan(h.followUpShare, 0.9)
        XCTAssertEqual(h.reciprocity, 1.0)
    }

    func testFloorNeedsOutcomes() {
        XCTAssertEqual(Feedback.calibratedFloor([]), AgentSide.matchFloor)
        let outs = (0..<30).map { Feedback.Outcome(lowerBound: Double($0) / 30, secondDate: $0 > 15) }
        XCTAssertLessThan(Feedback.calibratedFloor(outs), 0.6)
    }

    func testLoopbackDelivers() async throws {
        let (a, b) = Loopback.pair()
        try await a.send("hi"); try await a.send("there")
        let x = try await b.receive(), y = try await b.receive()
        XCTAssertEqual([x, y], ["hi", "there"])
    }
}
