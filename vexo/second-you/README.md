# Second You: agents that date first

Built at VexoHacks (YC, Nov 14 2026) for the Vexo Band.

Your **Second You** learns how you talk and what you value, on your iPhone. It then meets other people's agents before you
do. Agents test chemistry over a first chat, planning a date, and the hard questions (kids, faith, where to live). Your
photos and identity stay hidden. You hear about a match only when the confidence interval clears the bar, and you see each
other only if you both say yes. Your agent then plans the date, and nothing is booked until you tap Confirm. Once you're
together, a double press on your band sends a tap only your partner feels.

## Privacy: training never leaves the phone

| Data | Where it lives | Leaves the phone? |
|---|---|---|
| Your own lines (your side of conversations, what you type, quiz fixes) | Encrypted vault (`.completeFileProtection`, excluded from backups) | **Never** |
| Other people's words in your recordings | Read in memory to measure the exchange, then dropped | **Never** |
| Questionnaire: values and dealbreakers | Vault | **Never** |
| Learned profile, example bank, agent card | Vault | **Never** |
| Every model call (traits, agent messages, judging, audit, fidelity) | Apple's on-device model (Foundation Models) | **Never.** No cloud fallback |
| The chat messages your agent writes in a match | Sent to the other phone (Multipeer, or a relay that stores nothing) | Only these |
| Your verdict numbers for a match (3 scores + 2 flags) | Sent to the other phone | Only these |

"Training" builds the profile and example bank that steer Apple's on-device model. Foundation Models can't update its own
weights on an iPhone: custom adapters are trained on a Mac with Apple's adapter toolkit and shipped with the app.

## What's here

```
SecondYouKit/   Swift package (iOS 26 / macOS 26), the product code
  Style.swift      how you talk: example bank, sentence shape, pet phrases (no model)
  Dynamics.swift   how you behave in a conversation: talk share, follow-up questions, opening up, reciprocity (no model)
  Profile.swift    questionnaire (values and dealbreakers are asked, never inferred) and the agent's card
  OnDevice.swift   every Foundation Models call: traits, agent messages, judge, self-audit, fidelity
  Trainer.swift    the training step (rerun it as new lines arrive; this is the flywheel)
  Fidelity.swift   "Is this you?": below 0.7 agreement on dating situations, the agent can't enter matching
  Chemistry.swift  agent-to-agent matching across two phones; only messages and verdict numbers cross
  Feedback.swift   real outcomes calibrate the match floor; revealed preferences
  Vault.swift      the one encrypted file
sim/            Simulation harness on 20 virtual people (no real user data; cloud models allowed here)
demo-video/     How the demo video was made (Gemini Omni Flash clips, Nano Banana references, Gemini TTS, ffmpeg)
```

## Run it

```bash
cd SecondYouKit
swift test                        # 5 unit tests, no model needed
swift run secondyou-demo          # trains two people and runs a full match on this Mac's on-device model
```

`secondyou-demo` needs Apple Intelligence turned on. Without it, training does the model-free parts and skips the match.

## Does agent-to-agent matching work? The simulation

`sim/dating_sim.py`: 20 virtual people with hidden traits and a known "true compatibility" formula. Each agent sees only
a profile card. Each of 82 eligible pairs talks in 3 scenarios (246 conversations). An independent judge from a
different model family scores the transcripts.

| Signal | Rank correlation with true compatibility | AUC for top-quartile pairs |
|---|---|---|
| Judge + style matching | 0.71 | 0.90 |
| Independent judge | **0.73** | 0.89 |
| Language style matching alone | 0.03 | 0.67 |
| Agents rating themselves | 0.22 | 0.62 |

- **Dealbreakers:** 41 of 43 caught. Most of the 8 false alarms were real kids yes/no conflicts that the simulation's formula under-weighted.
- **Match rule:** matching only when the interval's lower bound is at least 0.6 gave 12 matches. 8 were truly top-quartile and 1 had a dealbreaker.
- **Two failures, fixed in `Chemistry.swift`:**
  - The future talk ended before every dealbreaker came up. It now continues until each one has been raised.
  - An agent invented a preference to be agreeable. Each phone now audits its own agent against its own card, reruns once, and blocks the match if it happens again.

Full results: `sim/results.json`.

## Notes

- The story shots in the demo video are AI-generated (Gemini Omni Flash). The app screens use real transcript lines from the simulation.
- The real Vexo Band gives quiet haptics and has no light. The pink glow in the video's opening is a concept.
- All code in this folder was written during the hackathon.
