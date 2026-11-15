# Replit agent prompt for the Vexo Match phone interface

Copy the text below into Replit Agent. Attach `IMPLEMENTATION_PLAN.md`, `RENDER_HANDOFF.md`, and the latest `server/app.py` and `server/schemas.py` if available. The API snapshot below reflects code inspected during development; the running backend's OpenAPI schema and agreed integration contract take precedence.

---

Build the complete mobile-first web interface for **Vexo Match**, an AI-assisted wearable dating experience. Deliver polished working software, including data integration and failure states, rather than a static mockup. This is the phone interface of an existing system, not a request to invent a separate matching platform.

## Product and system boundaries

Two people each own a wristband and a local Python hub that stands in for their phone's Bluetooth capabilities. The hub hears nearby enrolled bands, reports sightings to our shared Render server, and controls its owner's band. The server owns profiles, preferences, eligibility, matching, consent, notifications, and device coordination. Your app is the participant-facing web interface.

Architecture:

```text
Your mobile web UI ---- HTTPS ---- Render FastAPI API ---- Postgres
                                      |
Local Python hubs ----- HTTPS --------+
       |
       +---- Bluetooth ---- wristbands
```

Do not create another database, matching service, AI scoring service, identity system, or Bluetooth controller. Do not use Replit Database, Supabase, Firebase, or a new auth provider. Do not put provider keys or the Render management API key in this frontend. Read/write real data exclusively through the existing API. Work inside a frontend directory separate from the Python backend and hubs.

Build with React, TypeScript, Vite, and a coherent styling approach such as Tailwind. Use a query library for server state if useful. Pin dependencies through the lockfile. Prefer a small reliable dependency set. No native app build or app store deployment is needed. Installable PWA metadata and a basic app shell are welcome, but hardware remains controlled by the Python hub.

## Core experience

1. The person connects their app session to the shared server using an existing participant credential.
2. Home shows their approved profile readiness, dating status, and band/hub health.
3. The person explicitly chooses Open to dating; default is paused, based on server state.
4. A nearby compatible participant creates an anonymous suggestion. Show only the server-authorized anonymous content before mutual acceptance.
5. Both independently accept. Only then reveal the counterpart's approved public profile, shared interests, icebreaker, and assigned color if available.
6. When proximity evidence meets the configured threshold, hubs prepare both bands. Show a preparation state until both device acknowledgments succeed.
7. Both bands light in the same color. The interface helps the people recognize the shared color and asks them to tap their bands when they meet.
8. Both tap; the server records MET. Show a restrained celebration, followed by the authoritative next state.
9. Pause, decline, cancel, block, expiry, and connectivity loss all have clear outcomes. The UI never invents a successful transition.

Daily check-ins let a person submit their own notes. AI-generated profile changes remain proposals until explicitly accepted. Voice and profile learning support the core encounter rather than overwhelming Home.

## Visual direction

Design an elegant, warm, intimate product with strong typography and spacious composition. Use a soft ivory background, deep charcoal text, muted warm gray surfaces, and one restrained accent. Use the active pair's assigned color only as contextual feedback; it should not replace the overall visual system. Ensure yellow and white pair colors remain legible against light backgrounds using borders and contrast-aware text.

Avoid the generic dating-card swipe layout, crowded dashboards, glowing purple gradients, fake radar maps, and excessive glass effects. The product should feel calm, deliberate, and suitable for meeting someone in person. Use thoughtful copy, a small wordmark, large readable headings, rounded surfaces, and subtle tactile motion. Never suggest real haptic hardware has been activated by a browser animation.

The signature Home element can be a quiet band-shaped or circular color motif that changes with actual application state. While paused it is still; when searching it has a restrained pulse; when lighting is confirmed it displays the assigned color. This is a state illustration, not live radar or a representation of measured locations.

Design first for 390 px-wide phones, but support 320 px through desktop. Use bottom navigation on mobile: **Discover**, **Check-in**, **Inbox**, **You**. Adapt gracefully to wider screens. Support safe-area insets, large tap targets, keyboard navigation, visible focus, accessible labels, screen-reader announcements, reduced motion, and sufficient contrast. Color alone must never convey meaning.

Use real product copy and realistic information density. Do not fabricate photos, testimonials, user counts, activity, or compatibility percentages. Initial-based avatars are appropriate because the backend currently exposes no photo URL. Do not require external image generation or paid assets to finish.

## Screens and detailed behavior

### Session connection

Use a clean welcome screen explaining that a local hub handles the band. Allow a participant to enter their pre-issued participant token; make this feel like joining a private demo, not an unfinished login form. Support a configurable Render API origin. Keep endpoint editing under advanced connection settings rather than in the main participant flow.

Validate the token with GET `/api/me`. Store demo participant credentials in session memory or sessionStorage, never in source, query strings, analytics, or logs. Clear user-specific cache on disconnect or user switching. Do not request a Render API key, hub token, or operator token. Do not build fake sign-up or band-claim screens when those APIs are absent.

### Discover

Show a personal greeting, explicit Open/Paused control, clear status text, band/hub status, battery when known, and one central current-encounter card. Never show zero battery when the server value is null. Distinguish a lost backend connection from an offline hub or a band needing double-tap.

State-specific content:

| API state | UI |
| --- | --- |
| No match, paused | Calm resting state and explanation of how to enable discovery |
| No match, open | Searching state; no invented nearby counts or people |
| SCORING | “Checking compatibility”; do not show counterpart details |
| SUGGESTED, not accepted | Server-provided anonymous headline/detail, countdown, Accept and Decline |
| SUGGESTED, you accepted | “You accepted. Waiting for the other person”; allow cancellation |
| ACCEPTED | Public profile and shared interests; explain that lights activate when close is confirmed |
| LIGHTING | “Preparing your bands”; no claim that both lights are on |
| LIT | Large assigned color swatch with text name, counterpart, and tap-to-meet instruction |
| MET | “You met”; restrained confirmation, icebreaker if returned, then server-driven reset |
| Match disappears | Return to discovery and use relevant inbox event to explain expiry/cancellation if available |

Render the backend's proximity note: “Proximity last confirmed before lighting.” Connected bands stop advertising, so do not animate continuous approach, distance, or separation during lighting. Do not translate RSSI into exact meters. Do not claim the browser itself scans Bluetooth.

Add an accessible encounter detail sheet for the approved public profile, shared tags, goal, and icebreaker. A compatibility score is optional only if actually returned and authorized. The current API does not return one in the participant match projection; do not invent it.

Provide cancel and block actions through a small overflow menu with concise confirmation describing the consequence. Label app-based meet confirmation as “Confirm in app” and explain it is a fallback for band taps. It must use the real backend endpoint and only be available in LIT. Do not infer that both people have met from one person's action.

### Check-in

Use a short conversational prompt such as “What felt like you today?” Provide a real typed-note composer first. A submitted note produces an AI or deterministic profile proposal; clearly render the returned provider rather than claiming Claude ran when it did not.

Display current versus proposed summary, interests, values, and goal, with Accept changes and Keep current profile. Approval is a real API action. Explain that approving a profile change can end an active encounter. Preserve a draft if submission fails and prevent accidental double submission.

Do not ship a fake microphone button. The current API has transcript submission but no verified audio-upload or voice-session route. Show a disabled explanatory voice affordance only if helpful, or omit it until the backend/hub recording contract is supplied. A later browser-microphone implementation must request permission, upload to an agreed endpoint, and obtain a real transcript; it cannot silently send a placeholder transcript with source mic.

### Inbox

Show durable match notifications with title, body, read state, timestamp, and sensible empty states. Poll incrementally using the numeric cursor, paginate until caught up, deduplicate by notification ID, and mark read through the API. App foreground toasts and unread badges are notification stubs, not push notifications. Do not request system notification permission or claim background push exists.

A notification referring to an old match must not reveal an old or unaccepted profile. Resolve against current match state; explain when a suggestion is no longer active. Do not make an absent history API look like a working encounter-history feature.

### You

Show editable approved summary, interests, values, and relationship goal. Forms use server versions and validation. Human-readable tags map to lowercase hyphenated IDs. Require at least three interests and two values for discovery readiness, while respecting actual server validation and completeness fields.

Support explicit preferences: accepted genders, adult age range, and accepted relationship goals. Treat age, identity, and preferences as deliberate inputs, never AI inferences. The current edit routes do not support changing every identity field; render unsupported fields read-only instead of pretending to save them.

Show connected band number, hub status, last contact, and unknown-battery state in a compact device section. Pairing/enrollment remains managed outside this UI. Provide “How connection works” with a clear three-step explanation: hub listens, server matches, band lights.

## API integration contract

All participant calls use `Authorization: Bearer <participant-token>`. Identity is derived by the server, never supplied as a chosen user ID. Use a single typed API client with request timeouts, sanitized errors, and configurable base URL.

Current inspected routes:

| Method | Route | Request or behavior |
| --- | --- | --- |
| GET | `/api/me` | Own profile, preferences, status, hub and device summary |
| PUT | `/api/me/dating-status` | `{status: "open" or "paused", expected_version: number}` |
| PATCH | `/api/me/profile` | `{expected_version, summary?, interests?, values?, goal?}` |
| PATCH | `/api/me/preferences` | `{expected_version, genders?, age_min?, age_max?, accepted_goals?}` |
| GET | `/api/me/match` | `{match: null or object}` |
| POST | `/api/matches/{id}/respond` | `{accept: boolean}` |
| POST | `/api/matches/{id}/cancel` | End own encounter |
| POST | `/api/matches/{id}/block` | Block counterpart; counterpart ID is not exposed |
| POST | `/api/matches/{id}/confirm-met` | LIT-only labeled app fallback |
| GET | `/api/me/notifications?after=0` | `{items: [...], cursor: number}`; max 50 items per page in inspected code |
| POST | `/api/notifications/{id}/read` | Mark caller-owned item read |
| POST | `/api/me/voice-notes` | `{transcript: string, source: "typed"}` |
| GET | `/api/me/profile-proposals` | `{items: [{id, base_version, changes, provider}]}` |
| POST | `/api/me/profile-proposals/{id}/accept` | Apply proposal |
| POST | `/api/me/profile-proposals/{id}/reject` | Reject proposal |

Goal values are `long-term`, `casual`, and `friendship-first`. Profile summaries are limited to 300 characters; interests to eight tags; values to six tags. Tags match `^[a-z0-9][a-z0-9-]{0,30}$`. Note transcripts are 3–4000 characters. Check the live schema for any changes before integration.

GET `/api/me` currently returns these fields:

```typescript
type Me = {
  id: string;
  display_name: string;
  dating_status: "open" | "paused";
  status_version: number;
  age: number;
  gender: string;
  profile: null | {
    version: number; approved: boolean; complete: boolean;
    summary: string; interests: string[]; values: string[]; goal: string;
  };
  preferences: null | {
    version: number; genders: string[];
    age_min: number; age_max: number; accepted_goals: string[];
  };
  band_number: number | null;
  hub: null | {
    online: boolean; band_state: string;
    seconds_since_tick: number; battery: number | null;
  };
  demo_mode: "real" | "single_laptop" | "simulated";
};
```

Match projections always include `id`, `state`, `version`, `seconds_left`, `you_accepted`, and `you_tapped`. SUGGESTED adds anonymous `headline` and `detail`. Only ACCEPTED/LIGHTING/LIT/MET include `counterpart`, `shared`, `icebreaker`, `color`, `color_name`, `scorer`, and `evidence`. Some are nullable. The public counterpart contains `display_name`, `summary`, `interests`, `values`, and `goal`. LIGHTING/LIT/MET may include `proximity_note`, `lighting_session_id`, and `met_note`. Handle omitted fields safely, and never fill omitted identity fields from fixture data.

Profile/preferences/status edits use distinct version values. On HTTP 409, reload current data, preserve unsaved edits, and explain the conflict; do not retry an overwrite automatically. Responses to successful edits may be `{ok: true}` rather than the edited object: invalidate/refetch authoritative queries.

Poll current match at roughly one second while an encounter is active and the app is visible. Poll inbox at one second during the demo; coalesce requests and stop overlapping polls. Refresh Me periodically for hub health and after mutations. Pause foreground polling when hidden, refetch on visibility/focus/network recovery, and use bounded backoff for failures. Do not rely on browser background timers for server-side safety.

Only GET requests may be retried automatically. Show pending actions, prevent double submits, and reconcile current state before resubmitting uncertain writes. Abort old requests and isolate caches when account/session changes. A local countdown derives from the latest server seconds_left and elapsed monotonic time, then resynchronizes; reaching zero never authorizes a local lifecycle transition.

Handle 401 by returning to session connection, 403 as insufficient role, 404 as stale/unavailable content, 409 as a state/version conflict, 422 as validation feedback, and network/5xx failures with honest connection status. A fetch failure must never look like “no matches.”

## Real mode and preview mode

Real mode is the default whenever the Render URL and participant token are configured. Never silently fall back to mock data after an API failure.

Build a separate, explicitly labeled Preview mode so the UI can be evaluated before the backend URL is ready. Preview fixtures must use the same TypeScript response types and intentionally exercise every lifecycle state, incomplete profiles, unknown battery, offline hubs, empty inbox, stale proposals, and network failure. No real credentials or real personal data in fixtures. Preview is client-only and cannot create real matches, sightings, or device commands.

Keep the Preview badge visible on every preview screen. For live data, use `demo_mode` and match evidence to label simulated or single-laptop demonstrations without implying real radio detection. Do not expose raw RSSI or developer controls in the participant UI.

## Deployment and backend coordination

Production output must be static files under a documented build directory, suitable for FastAPI to serve on Render. Preserve `/api/*` routes and ensure SPA fallback does not intercept API errors. Use relative API paths for the final same-origin deployment.

During Replit preview, configure a public API origin, for example through `VITE_API_BASE_URL`; it is public configuration, not a secret. Cross-origin authenticated requests require the backend owner to allow the exact preview origin, needed methods, and Authorization/Content-Type headers. Do not work around CORS using no-cors requests or by disabling browser security. If preview origins change, document that coordination point. Avoid a development proxy that can forward credentials to arbitrary hosts.

If backend routes are missing or differ, create an integration-gap note listing the exact method, path, required fields, and desired behavior. Ask the backend owner to implement or confirm it; do not build a competing server. The current snapshot lacks sign-up, photo upload, full history, audio upload, and verified live voice-session APIs. Do not pretend those features are functional.

Provide a frontend README describing installation, development, tests, build, API configuration, demo session setup, production static serving, CORS requirements, and known unsupported features. Do not deploy a second persistent backend or database through Replit.

If PWA offline caching is added, cache only public static assets. Never cache authenticated API responses, participant tokens, profiles, or notifications in the service worker. Offline UI must show stale data as stale; no offline acceptance queue, background dating-status changes, or hardware claims.

## Quality and acceptance

Finish all screens with working navigation, loading skeletons, empty states, validation, and meaningful errors. Keep transitions subtle and respect reduced-motion settings. Preserve user drafts across recoverable errors without storing credentials in draft data.

Verify:

1. Two independent browser sessions show different users and receive the same encounter through the API.
2. Paused state remains paused until the server confirms a change; an unavailable backend cannot be mistaken for successful pausing. Explain that an unconfirmed pause has not reached the server.
3. Before both accept, no counterpart name, photo, detailed facts, color, or private profile is rendered.
4. One acceptance shows waiting. Mutual acceptance reveals only fields actually returned.
5. LIGHTING and LIT are distinct; no fake proximity or device progress is generated locally.
6. Pause, decline, cancel, block, expiry, and old notification clicks recover cleanly.
7. Typed check-in produces a real proposal; accepting/rejecting uses the actual route; 409 preserves edits.
8. Polling deduplicates inbox items, cleans up on navigation/unmount, and cannot leak one account's data to another.
9. No browser errors, horizontal overflow at 320 px, inaccessible controls, or unreadable pair colors.
10. Production build succeeds, key interaction tests pass, and the deployed integration works when the backend URL is supplied.

Use focused tests for API mapping, privacy before acceptance, conflict handling, and lifecycle UI states. Inspect rendered screens at phone and desktop sizes. Do not count fixture-only tests as verified Render integration.

At completion, return a preview link, source/build locations, setup commands, tested flows, and any precise backend blockers. Distinguish live integrated behavior from preview fixtures. Make reasonable design decisions and complete the usable interface without stopping for approval of ordinary layout choices.
