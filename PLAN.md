# AI Personal Assistant — Development Plan

Assignment: callkaro.ai take-home. Google Calendar + Tasks, voice + text, 24h wall-clock / ~15 real working hours.

## 1. Architecture

```
Next.js (Vercel, thin client)          FastAPI (Railway/Fly, no spin-down)         Google
──────────────────────────              ──────────────────────────────────          ──────
Chat UI, mic button (Web Speech)  ──▶   /auth/login, /auth/callback         ──▶    OAuth2
JWT stored client-side, short TTL       (issues short-lived JWT)
Renders clarify / propose / result ──▶  /chat   (LangGraph, single-shot,
Confirm/Cancel buttons             ◀──          no checkpointer, no interrupt())
                                    ──▶  /execute (hardened handler, see §4)
                                          │
                                          ├─ LangGraph: router → slot-fill →
                                          │   datetime resolve → match → propose
                                          ├─ Calendar tool wrappers (CRUD)
                                          ├─ Tasks tool wrappers (CRUD)
                                          └─ Postgres (Supabase): refresh tokens only
                                             (no checkpointer — nothing to persist)
```

No LangGraph checkpointer, no `interrupt()`. Every `/chat` call is fully self-contained: client sends message + bounded recent history + `last_referenced_entity` + current datetime + IANA timezone; server resolves everything fresh and returns one of three response types. State lives in the client, not the graph.

**Auth**: FastAPI owns the full OAuth2 flow (Testing-mode consent screen, add self as test user). On callback, issue a short-lived JWT (e.g. 30–60 min) to the frontend as a bearer token — not a cross-domain cookie. Frontend attaches `Authorization: Bearer <jwt>` on every request. One-line tradeoff for the README: avoids SameSite/CORS-cookie complexity across two domains; token kept short-lived and non-persistent (memory/sessionStorage, not localStorage) to bound XSS exposure.

## 2. Wire contracts (decide first, build once)

### `POST /chat` request
```json
{
  "message": "move my Friday meeting to Monday morning",
  "recent_history": [ /* last 6–10 turns, {role, content} */ ],
  "last_referenced_entity": { "type": "event", "id": "...", "summary": "Dentist, Fri 3pm" } ,
  "now": "2026-07-22T14:03:00+05:30",
  "timezone": "Asia/Kolkata"
}
```
`last_referenced_entity` is set by the client from the most recent `proposed_action` or matched entity — this is what resolves "move **it** to Monday" instead of hoping the model infers a referent from a fuzzy history window.

### `POST /chat` response — discriminated union
```json
{ "type": "clarify", "message": "What time on Monday should I move it to?" }
{ "type": "propose", "message": "Move 'Dentist' from Fri 3:00pm to Mon 9:00am — confirm?",
  "proposed_action": {
    "request_id": "client-generated-uuid",
    "action": "calendar.update",
    "entity_id": "google-event-id",
    "params": { "start": "2026-07-27T09:00:00", "end": "2026-07-27T09:30:00", "timeZone": "Asia/Kolkata" }
  } }
{ "type": "result", "message": "Done — moved to Monday 9:00am." }
{ "type": "error", "message": "I couldn't find a Friday meeting to move." }
```
Frontend renders Confirm/Cancel **only** on `type: "propose"`; `clarify` just awaits a free-text reply; `result`/`error` are terminal for that turn.

### `POST /execute` — one hardened handler, not two patches
Body: the exact `proposed_action` object echoed back verbatim (never re-derived by an LLM at execute time).

```
1. dedupe check   — key = proposed_action.request_id (per-user scoped), NOT a content hash,
                     so two genuinely-identical user-intended actions aren't falsely blocked.
                     Cache hit → replay the stored result (not a generic "already done").
2. re-validate    — fetch entity_id from Google; 404/410 → typed "no longer exists" error,
                     not a 500. (Race window: propose and confirm are separate requests.)
3. act            — call the Calendar/Tasks tool wrapper.
4. cache + return — store result under request_id (TTL ~10 min), return typed result envelope.
```

## 3. Datetime & timezone — first-class, most-tested component

- Client sends `now` + IANA `timezone` on every `/chat` call. Server never assumes its own clock/TZ (Railway host is UTC).
- **Do not hand-roll UTC conversion.** Resolve relative expressions ("tomorrow 3pm") into a *local wall-clock* datetime string, and pass it to Google's API as `dateTime` + a separate `timeZone` field (IANA name). Google converts to UTC server-side — this removes an entire bug class (DST, offset-sign errors) rather than testing around it.
- Explicit rules to encode and test (ambiguity must be a decision, not vibes):
  - "Friday" said on a Friday → today, unless that time has already passed → then next Friday.
  - "Monday morning" → default to 9:00am unless otherwise specified.
  - "this week" → Mon–Sun (or today–Sun?) range for read queries — pick one, document it.
- **pytest suite, primary target**: pure-logic datetime resolver, no I/O. Cases: "tomorrow 3pm" → exact ISO, "next Monday", "this week" range, same-day-weekday-name edge case, missing-time defaults. This is the single highest-signal test given "AI reasoning and reliability" is criterion #1, and it guards the bug most likely to surface live on camera (wrong timezone → every relative time off by hours).

## 4. Read → match → confirm — symmetric across Calendar AND Tasks

Build as one shared function, parameterized by entity type, so Tasks can't silently become the afterthought (all example commands lean Calendar-heavy):
```
resolve_target(entity_type: "event"|"task", query: str) -> Match | Ambiguous | NotFound
```
- `Match` → single candidate → proceed to propose.
- `Ambiguous` → return `clarify` with the candidates ("Which one — 3pm Dentist or 5pm Dentist follow-up?").
- `NotFound` → return `error`, don't let the model invent an ID.

## 5. "John" / Contacts — resolved, not deferred

Default path (zero extra cost, ships now): slot-fill asks **"What's John's email?"** — this doubles as a live demonstration of the `clarify` flow, not a downgrade.
Google People API (read-only contact lookup) is a **stretch item only**, attempted after Calendar+Tasks core is fully solid (hour 12+ of real work), not committed scope. If added, it requires an extra consent scope + re-consent by test users — budget that cost explicitly if pursued.

## 6. Scope

**In**: Google Calendar (CRUD) + Google Tasks (CRUD), text input, voice input/output via browser Web Speech API (Chrome/Edge; documented limitation for Safari/Firefox).
**Out**: Gmail, Drive, Docs, Sheets, Maps. Contacts = stretch only (§5).

## 7. Failure classes — one distinct, graceful message per brief-named case

| Class | Handling |
|---|---|
| Ambiguous request | `clarify` response, disambiguation candidates listed |
| Missing information | `clarify` response, ask the specific missing slot |
| Invalid operation | `error` response (e.g., target not found, past-date conflict) |
| API failure (Google 4xx/5xx) | `error` response, retried once for transient 5xx, else surfaced plainly |
| Auth expired mid-session | 401 → frontend triggers re-login, does not silently fail |

## 8. Tech stack

- Backend: FastAPI, LangGraph (stateless graph, no checkpointer), `google-api-python-client`, `google-auth`, Postgres via Supabase (refresh tokens only).
- Frontend: Next.js (App Router), plain fetch (no next-auth — FastAPI owns OAuth), Web Speech API (`SpeechRecognition` + `SpeechSynthesis`).
- Tests: pytest — datetime/timezone resolver (primary), tool-wrapper unit tests (mocked Google client).
- Hosting: Vercel (frontend), Railway or Fly.io hobby tier (backend — must not spin down), Supabase (Postgres).

## 9. Timeline — session-relative, not a fictional 0–24 clock

(Anchors are "hours of real work," across however many sessions/sleep breaks you actually take.)

1. **Work session 1 (~3h)**: Google Cloud project + consent screen (Testing, self as test user) + enable Calendar/Tasks APIs → deploy empty skeletons to Vercel + Railway for stable HTTPS URLs → **auth spike**: login → JWT issued → one real `calendar.list` call, end to end. This is the go/no-go checkpoint for the split-service approach.
2. **Work session 2 (~3–4h)**: Calendar + Tasks tool wrappers (CRUD, mocked-then-real), shared `resolve_target` match function.
3. **Work session 3 (~4h)**: LangGraph graph (router → slot-fill → datetime resolve → match → propose), `/chat` envelope, `/execute` hardened handler (§2). Test via curl/Postman before touching frontend.
4. **Work session 4 (~3h)**: Next.js chat UI — message list, mic button, Confirm/Cancel rendering per envelope type, simple upcoming-events/tasks side panel.
5. **Work session 5 (~2h)**: pytest suite (datetime resolver + tool wrappers), failure-class pass (§7), fix what breaks.
6. **Rehearsal checkpoint (2h before your planned recording slot, not a fixed "hour 17")**: full dry run of the demo script (§10). Fix anything that breaks live, re-rehearse once.
7. **Final session (~2h)**: README (§11), record demo video, deploy check, submit.

## 10. Demo video script (5–10 min) — sequenced to hit the rubric on camera

1. Text command golden path: create a meeting ("schedule with X tomorrow 3pm").
2. Voice command: same category, spoken.
3. Ambiguous/missing-info request resolved via a `clarify` follow-up (e.g., "schedule a meeting" with no time).
4. Update or delete with explicit confirm/cancel shown.
5. Weekly read ("what does my calendar look like this week").
6. One deliberately-triggered graceful failure — e.g., confirm a delete, but the event was already removed elsewhere first → shows the §2 staleness handling live. This is a controlled demonstration of robustness, not an accident.

## 11. README structure — mirrors the evaluation criteria

- Overview / architecture diagram (§1)
- Setup instructions
- **Reliability & AI reasoning** — datetime/timezone approach, read→match→confirm, stateless confirm design
- **Error handling** — the failure-class table (§7)
- **Production readiness** — auth token lifetime tradeoff (bearer vs cross-domain cookie), refresh-token storage (Postgres now, note: encrypt at rest / secrets manager in a real production deployment)
- **Known limitations** — OAuth Testing-mode (test-user list or rely on demo video), Web Speech API is Chrome/Edge-only, Contacts/attendee-email resolution is manual (stretch: People API)
- Demo video link
