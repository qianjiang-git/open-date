import Foundation

/// The flywheel, on the device: real outcomes calibrate the match floor and update what the user actually likes.
public enum Feedback {
    public static let targetPrecision = 0.6
    public static let minOutcomes = 20

    public struct Outcome: Codable, Sendable {
        public var lowerBound: Double
        public var secondDate: Bool
        public init(lowerBound: Double, secondDate: Bool) { self.lowerBound = lowerBound; self.secondDate = secondDate }
    }

    /// The lowest interval bound at which at least `targetPrecision` of past matches led to a second date.
    public static func calibratedFloor(_ outcomes: [Outcome], default d: Double = AgentSide.matchFloor) -> Double {
        guard outcomes.count >= minOutcomes else { return d }
        for thr in Set(outcomes.map(\.lowerBound)).sorted() {
            let above = outcomes.filter { $0.lowerBound >= thr }
            if above.count >= 5, Double(above.filter(\.secondDate).count) / Double(above.count) >= targetPrecision { return thr }
        }
        return d
    }

    /// What they do, not what they say.
    public static func record(_ p: inout DatingProfile, accepted: Bool, other: TraitsReading? = nil, dateRating: Double? = nil) {
        if accepted { p.revealed.accepted += 1 } else { p.revealed.skipped += 1 }
        if accepted, let h = other?.humor { p.revealed.likedHumor[h, default: 0] += 1 }
        if let r = dateRating { p.revealed.dateRatings.append(r) }
    }
}
