# Follow up prompt for the Vexo Match Expo phone app

Paste the text below into the same Replit Agent conversation after the original phone-interface prompt. Attach the latest backend contract and reference-kit protocol files. This follow-up changes the runtime and hardware responsibilities; it preserves the existing visual direction, product flow, privacy rules, and Render integration.

---

We are updating the requirements: build **a React Native and Expo phone app that can replace the Python Bluetooth hub**, rather than only a mobile website. Preserve useful existing interface work and port its components and styles appropriately. Do not claim the current web app already supports direct bracelet connections.

## The intended experience

Two people open the same app/project link on two different physical phones. They use separate accounts and each links a different owned Vexo bracelet. Both talk to the same Render API and Postgres database. Their phones discover nearby enrolled advertising bracelets and connect only to their own bracelets when lighting or recording is required.

```text
                    Same app project
                     /          \
                Phone A        Phone B
                User A         User B
                   |              |
                 BLE            BLE
                   |              |
              Bracelet A     Bracelet B

               Both phones -- HTTPS --> Render API --> Postgres
```

The shared app URL identifies the app, not the user. Never create a shared account from that URL, reuse one token for everyone, or generate a new permanent user on every app launch.

## Build feasibility before promising a QR flow

Use a native BLE library compatible with the chosen Expo SDK, such as `react-native-ble-plx`, after checking current official documentation and maintained compatibility. This library requires native code and is not available in standard Expo Go. Use an Expo development build with the required native library and configuration plugin. Do not claim that scanning an ordinary Expo Go QR code provides real Bluetooth.

Explain the actual physical-device setup:

1. Install the appropriate signed development build on each test phone.
2. Open the shared development project link in that installed development client, or use an installed preview build with a bundled JavaScript app.
3. Each person independently authenticates and connects their assigned bracelet.

Android and iOS require different installation artifacts. Verify signing, device registration, credentials, build access, and any applicable costs before promising delivery on iPhones. If Replit cannot run the native toolchain, prepare the complete source, Expo configuration, EAS profiles, and reproducible build instructions. Do not present a web preview as proof that native BLE works. Do not create paid builds or external accounts without authorization.

Development bundle delivery is separate from Render API connectivity. Event Wi-Fi may block phone-to-development-server LAN access; document a supported tunnel workflow or use an installable preview build with bundled JavaScript. The two phones need internet access to Render but do not need a direct network link to each other.

Keep a clearly labeled UI-preview adapter for environments without native BLE. Guard native module imports so unsupported runtimes show a useful explanation rather than crashing. Preview must never send fake radio evidence to the live hub endpoint.

## Separate user identity, sessions, and bracelet ownership

Maintain distinct records/concepts:

- Server-issued stable user ID: owns profile, preferences, and dating status.
- Participant session: authorizes interface actions for that user.
- Hub/controller credential: authorizes that phone to report sightings and execute commands for its assigned bracelet.
- Registered bracelet number: links the physical device to the account on the server.
- Local app installation ID: optional diagnostic/controller identity; never substitutes for authentication or a user ID.

The backend currently has separate user and hub token roles. GET `/api/me` uses the participant token; POST `/api/hub/tick` uses the hub token. Do not send participant tokens to hub endpoints or put operator credentials in the mobile app. For the private demo, accept separately provisioned credentials through a secure setup screen. Production sign-in or controller-credential exchange requires an agreed backend endpoint; do not invent a working exchange locally.

Use native secure credential storage, for example Expo SecureStore. Account switches clear cached participant data, stop previous scans and connection ownership, and require the newly assigned hub identity. Closing a session should best-effort pause/cancel with the server before releasing BLE resources; if the server cannot be reached, say the pause was not confirmed and rely on heartbeat expiry rather than claiming success.

The ownership mapping is server-authoritative. A person cannot claim any discovered bracelet by changing a client-side value. Current code uses controlled enrollment rather than a verified self-service claim API: show the server-assigned bracelet and guide the user to connect it. Add a self-service enrollment screen only after the backend implements authorization and conflict handling.

On the server, one bracelet cannot belong to two users, and one active controller must own a user's bracelet. Coordinate a controller handover/revocation mechanism before allowing a phone and an old laptop hub to report concurrently. Until then, explicitly stop the laptop hub before using native mode. Merely generating a new session ID does not prove the old controller was revoked.

## Native Bluetooth implementation

Build a serialized Bluetooth service independent of UI components. Screens consume its status; route changes must not create duplicate scanners or connections. Request the permissions required for the actual Android/iOS versions and explain Bluetooth-off, permission-denied, needs-double-tap, and disconnected states.

Use the existing contract and SDK behavior as the source of truth:

- BLE service UUID: `254f0001-df82-4a9c-a2b5-563a0f6b2021`.
- RX write characteristic: `254f0002-df82-4a9c-a2b5-563a0f6b2021`.
- TX notification characteristic: `254f0003-df82-4a9c-a2b5-563a0f6b2021`.
- Advertising manufacturer data, company `0xFFFF`: tag `0x4F`, protocol-major byte, little-endian band number in bytes 2–3.

These identifiers are not sufficient by themselves to send commands. Inspect `vexo-open-kit/contract/contract.md`, the JavaScript SDK and transport boundary, and the tested Python hub. Reuse portable protocol parsing/encoding where possible. The web SDK transport may depend on `navigator.bluetooth` and cannot simply be imported unchanged into React Native. Implement a native transport adapter or tested minimal protocol layer. Subscribe to TX before commands; serialize sequence-correlated requests, enforce timeouts, validate responses, and verify the reported band number after every connection before any light or microphone command.

Account for native-platform manufacturer-data encoding, scan callback duplication, UUID normalization, MTU/frame limits, and subscription cleanup. Do not parse a platform device identifier or BLE MAC address as the account's stable band identity. Test advertisement decoding against known packets and the real hardware.

Connect only to the currently authenticated participant's configured owned bracelet. Scan only the explicitly authorized demo roster according to the agreed kit/demo policy, and ignore unregistered observations for matching. Never connect to another person's bracelet to measure proximity or control its light.

## Discovery and lighting constraints

The current firmware does not scan for other bracelets. The phone scans; the bracelet advertises. An idle bracelet is invisible until a connection window opens. Double-tap opens 60 seconds; a normal disconnection opens 120 seconds. A controlled connect/disconnect renewal near 90 seconds may keep an open participant's band discoverable, but verify it on actual phones before depending on it.

While advertising, the bracelet blinks blue. While connected, it stops advertising. Consequently, discovery and connected lighting are distinct phases:

1. BEACON: owner bracelet disconnected and advertising, phone scans others, periodically renews its own band window.
2. ACCEPTED: both people agreed; phones continue scanning and wait for fresh close evidence.
3. LIGHTING: each phone connects only to its own bracelet and applies the server's desired command.
4. LIT: both current command acknowledgments succeeded; show the shared color and subscribe to taps.
5. MET: after both current-session taps, show the server-requested green flash.
6. Return to BEACON if open, or idle if paused.

During LIT the pair's advertisements disappear. Do not pretend to keep measuring separation. End through taps, cancellation, pause, device loss, or timeout. RSSI thresholds need smoothing and calibration; never promise one-meter accuracy. Respect microphone ownership of the blue LED and never override a recording session.

Prefer a foreground-only physical demo first. Do not assume JavaScript timers, one-second HTTPS polling, command leases, or repeated scan callbacks continue when the app is backgrounded or the phone locks. On leaving the foreground, best-effort stop encounter lighting and disconnect, invalidate local pending actions, and let server heartbeat loss terminate the encounter. Document that abrupt OS suspension may prevent cleanup; do not claim a firmware watchdog exists. On return, reacquire permissions/status and reconcile current server commands before resuming. Broader background BLE needs a separately validated native/platform design.

## Hub protocol and server integration

Port the Python hub's responsibilities into mobile services. Read the latest `/api/hub/tick` schema and actual response, plus the desired-state lifecycle, before coding. Reuse the server's existing semantics rather than inventing a second command protocol.

The inspected request includes a source-session ID, increasing tick sequence, own-band health, timestamped directed observations, command acknowledgments, and tap events. Observations carry real RSSI, sample count, observation sequence, sample age, and source `real_beacon`. Simulated/mirrored sightings belong only in operator-controlled demo paths, never mislabeled as real mobile radio reports.

Implement:

- Foreground periodic tick with timeout, bounded backoff, and no overlapping requests.
- Freshness-preserving observation queues; retrying a request must not make an old radio reading fresh.
- Pending acknowledgment and tap delivery until the server acknowledges receipt.
- Versioned desired-state handling, serialized BLE writes, local monotonic lease expiry, and stale-command rejection.
- APPLIED only after the actual device response; no optimistic “both bands lit.”
- Recovery that fetches current desired state instead of replaying old colors after reconnect.
- One connection owner so advertising-renewal timers cannot interrupt lighting or voice.

Keep all existing participant API behavior from the earlier prompt: mutual acceptance before profile reveal, version-guarded edits, notifications, check-in proposals, privacy, and labeled app meet-confirmation fallback. The same Render backend serves both phone installations.

Do not implement native voice streaming until the core identity, scan, tick, and lighting path works. Typed check-ins remain functional. Band audio capture/transcription requires a separately agreed backend route and provider adapter; no credentials in public Expo configuration.

## UI changes and source layout

Preserve the elegant warm visual direction and four tabs: Discover, Check-in, Inbox, You. Add a polished connection setup with independent server session and band status. Suggested steps: Join private demo, Verify your assigned bracelet, Enable Bluetooth, Connect and verify, Ready to discover.

Show participant name, assigned bracelet number, current connection mode, and useful recovery instructions. Do not clutter the main flow with tokens, radio values, or developer controls after setup. Use native navigation, safe areas, accessible controls, and platform-appropriate keyboard behavior.

Suggested module boundaries:

```text
mobile/
  app/                         screens and navigation
  src/api/                     typed participant and hub API clients
  src/auth/                    role-separated secure credential storage
  src/ble/                     native transport, protocol, scanner, connection actor
  src/controller/              tick loop, observations, leases, taps, lifecycle
  src/components/              shared native interface components
  src/preview/                 clearly labeled fixture adapters
  app.config.ts                permissions and verified BLE configuration plugin
  eas.json                     development and preview build profiles
  README.md                    setup, device install, build, recovery, limitations
```

Export public configuration such as API origin through appropriate Expo config. Expo public environment variables are bundled client data, so never place private signing credentials, provider keys, database URLs, or Render management keys there. Document unresolved signing/build requirements instead of fabricating an installation link.

## Build order and acceptance

1. Preserve the existing UI design and map existing API calls into a native app.
2. Verify native dependency compatibility; produce build configuration and physical-device installation instructions.
3. Connect two independently authenticated phone sessions to Render. Account A must never show account B's private profile or drafts.
4. Provision each phone's own hub role and assigned band mapping through the agreed demo enrollment flow.
5. On physical hardware, scan the authorized roster, connect the assigned band, verify identity, issue a test LED command, and cleanly disconnect.
6. Prove 120-second discovery-window renewal and repeated RSSI observations on the chosen phones; record actual results and limitations.
7. Integrate sighting ticks, mutual acceptance, close gating, both LED acknowledgments, tap-to-met, and cleanup.
8. Exercise permission denial, Bluetooth off, backgrounding, restart, duplicate ticks, stale commands, server loss, one-band failure, and attempted duplicate controller ownership.
9. Demonstrate both phones running the same app version with different accounts and different bracelets. Confirm no cross-control, data leakage, shared credentials, or invented proximity.

If only UI preview or simulator behavior can be tested in Replit, deliver it with native source and precise remaining hardware/build blockers. Mark physical BLE behavior unverified until tested on real phones; simulator success is insufficient. Do not silently fall back to laptop control or simulated radio while presenting a phone-only experience.

Return the source changes, exact dependency versions, build profiles, installation steps for each platform, tested API revision, integration gaps, and clear real-device validation results. Continue all independent UI and API work while waiting for device/signing inputs. Ask only for indispensable missing inputs: target phone platforms, authorized bracelet identities, build/signing access, Render URL, and independently provisioned demo sessions.

## References to verify during implementation

- [Expo development builds](https://docs.expo.dev/develop/development-builds/introduction/)
- [Expo custom native code](https://docs.expo.dev/workflow/customizing/)
- [React Native BLE PLX maintained repository](https://github.com/dotintent/react-native-ble-plx)
- Local `IMPLEMENTATION_PLAN.md`, `RENDER_HANDOFF.md`, `server/app.py`, `server/schemas.py`, the Python hub, and the Vexo contract/SDK.
