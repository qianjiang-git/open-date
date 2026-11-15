import Foundation

/// Training, entirely on the device. "Training" here means building the profile and example bank that condition
/// Apple's on-device model; Foundation Models cannot update its own weights on an iPhone (custom adapters are trained on
/// a Mac with Apple's adapter toolkit and shipped with the app). Nothing here makes a network request.
public enum Trainer {
    public struct Consent: Sendable {
        /// Let the on-device model read the user's own lines for humor, conflict style and topics.
        public var traits: Bool
        public init(traits: Bool) { self.traits = traits }
    }

    /// The flywheel step: run it again whenever new own lines, transcripts or questionnaire answers arrive.
    public static func train(name: String, lines: [OwnLine], questionnaire: [Question: Answer], faithName: String? = nil,
                             transcripts: [[Turn]] = [], consent: Consent, previous: DatingProfile? = nil) async -> DatingProfile {
        var p = previous ?? DatingProfile(name: name)
        p.name = name
        p.version += 1
        p.trainedAt = Date().timeIntervalSince1970
        p.values = questionnaire.filter { $0.key.options.contains($0.value.answer) }
        p.faithName = faithName
        p.style = Style.traits(lines)
        p.phrases = Style.phrases(lines)
        p.examples = Array(Style.bank(lines).prefix(60))
        if !transcripts.isEmpty, let h = Dynamics.measure(transcripts) { p.habits = h }
        if consent.traits, p.examples.count >= 10 {
            p.traits = (try? await OnDevice.readTraits(p.examples)) ?? p.traits      // unavailable: keep what we had
        }
        return p
    }
}
