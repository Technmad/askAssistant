<div align="center">

# AI Personal Assistant
### Google Calendar & Tasks, by voice or text

![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.139-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1.2-1C3C3C)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-Llama%203.1%20%2B%20Whisper-F55036?logo=groq&logoColor=white)
![Google APIs](https://img.shields.io/badge/Google-Calendar%20%C2%B7%20Tasks%20%C2%B7%20People-4285F4?logo=google&logoColor=white)

A natural-language assistant for Google Calendar and Google Tasks — with a full read → confirm → execute loop so nothing touches your real calendar without you saying "yes."
Built for the callkaro.ai take-home assignment.

**[Live App](https://ask-assistant-three.vercel.app)** &nbsp;·&nbsp; **[Backend API](https://askassistant-production.up.railway.app)** &nbsp;·&nbsp; **Demo Video** _(link coming soon)_ &nbsp;·&nbsp; **[Source](https://github.com/Technmad/askAssistant)**

</div>

---

> **Access note:** Google's OAuth consent screen for this project is in **Testing** publishing status (see [Known limitations](#known-limitations)). If login doesn't work for you, that's why — watch the demo video, or ask to be added as a test user.

---

## Contents

- [What it does](#what-it-does)
- [CRUD coverage](#crud-coverage)
- [Beyond the core requirements](#beyond-the-core-requirements)
- [Architecture](#architecture)
- [Setup](#setup)
- [Reliability & AI reasoning](#reliability--ai-reasoning)
- [Error handling](#error-handling)
- [Production readiness](#production-readiness)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Project structure](#project-structure)
- [Tech stack](#tech-stack)

---

## What it does

Type or speak things like:

- "Schedule a meeting with John tomorrow at 3pm"
- "What's on my calendar this week?"
- "Move my Friday meeting to Monday morning"
- "Create a task to submit the report next Monday"
- "Mark my grocery task as completed"
- "Delete my dentist appointment"
- "Show me all tasks due this week"

Every create, update, delete, or complete is **proposed first** — the agent replies with a plain-language summary of exactly what it's about to do, and only an explicit **Confirm** click executes it against your real Calendar/Tasks. **Cancel** ends it with nothing touched.

A typical exchange:

```
you        Schedule a meeting with Priya tomorrow at 3pm

assistant  Create "Meeting with Priya" with priya@example.com on
           Thursday Jul 24 at 03:00 PM — confirm?
           [ Confirm ]  [ Cancel ]

you        (clicks Confirm)

assistant  Created "Meeting with Priya" on Thursday Jul 24 at 03:00 PM.
```

If something's ambiguous or incomplete, it asks — it never guesses:

```
you        Delete the meeting with Priya

assistant  Which one did you mean — "Meeting with Priya" (Thu Jul 24,
           03:00 PM); "Meeting with Priya" (Fri Jul 25, 11:00 AM)?

you        the 11am one

assistant  Delete "Meeting with Priya" — confirm?
```

The follow-up reply is matched against what was *actually* offered (by time, by ordinal position, or by copying the label back) — not re-derived from scratch, which is what would otherwise leave a one-word reply like "the 11am one" with nothing to match against.

## CRUD coverage

Full create/read/update/delete, implemented identically for both services so Tasks never trails Calendar as the less-tested half:

| Operation | Google Calendar | Google Tasks | Example command |
|---|---|---|---|
| **Create** | `calendar.create` | `task.create` | *"Schedule a meeting tomorrow at 3pm"* / *"Create a task to submit the report Monday"* |
| **Read** | `calendar_read` (date-range list) | `task_read` (open-task list) | *"What's on my calendar this week?"* / *"Show me tasks due this week"* |
| **Update** | `calendar.update` (time, title) | `task.update` (title, due date) | *"Move my Friday meeting to Monday morning"* |
| **Delete** | `calendar.delete` | `task.delete` | *"Delete my dentist appointment"* |
| **Complete / Reopen** | — | `task.complete` / `task.reopen` | *"Mark my grocery task as completed"* / *"Unmark it"* |

Every mutating path runs through the same `resolve_target()` fuzzy-matcher ([`app/services/resolve.py`](backend/app/services/resolve.py)) and the same hardened `/execute` dispatcher ([`app/agent/execute.py`](backend/app/agent/execute.py)) — one code path per concern, not one per intent.

## Beyond the core requirements

The assignment explicitly favors a focused, polished feature set over breadth for its own sake. One additional integration was added — deliberately, not as a checkbox exercise:

- **Google People API (read-only contacts lookup).** The assignment's own flagship example is *"Schedule a meeting with **John**..."* — without contact resolution, that always stops to ask for John's email, every time. `app/services/contacts.py` checks both saved contacts and Gmail's auto-suggested "Other contacts" and resolves a confidently-matched name to an email automatically, falling back to asking only when the person genuinely isn't found (or the match is ambiguous — inviting the wrong person is worse than one extra question).

Gmail, Drive, Docs, Sheets, and Maps were deliberately **not** added. None has an honest, non-contrived tie-in to a Calendar/Tasks assistant, and forcing one in would trade the reliability/UX polish work for surface-level breadth. Contacts was the one exception because it's load-bearing for the assignment's own headline example — everything else stayed out on purpose.

## Architecture

```
Next.js (Vercel)                        FastAPI (Railway)                     Google APIs
─────────────────                        ──────────────────                    ───────────
Chat UI (text + voice)      ────────▶    /auth/login, /auth/callback  ──────▶ OAuth2
 • Web Speech API (native)                (issues a short-lived JWT)
 • Whisper fallback (Safari/Firefox)
                             ────────▶    /chat   (LangGraph agent)
                             ◀────────      • Groq LLM: intent + slot extraction ONLY
Confirm / Cancel UI                         • deterministic code: dates, entity
                             ────────▶        matching, conflict checks, contacts
                                           /execute (dedupe + act, idempotent)
                                             │
                                             ├─ Calendar API (CRUD)
                                             ├─ Tasks API (CRUD)
                                             ├─ People API (contact lookup)
                                             └─ token store (SQLite locally)
```

### Why it's built this way

**The LLM only extracts language — it never decides anything reliability-critical.** Groq (`llama-3.1-8b-instant`, configurable via `GROQ_MODEL`) reads the user's message and pulls out an intent plus raw slots (a title, a phrase like "tomorrow 3pm", who to invite). It never resolves a date, never invents an entity ID, never decides a scheduling conflict. All of that is deterministic Python, independently unit-tested apart from the LLM. This split is the main answer to "how is this reliable" — the parts most likely to silently misfire never touch the model.

**Every mutation is propose → confirm → execute, never fire-and-forget.** The agent returns a structured `proposed_action`; the frontend renders it with Confirm/Cancel; only an explicit confirm calls `/execute`. There's no LangGraph checkpointer and no server-side session — the whole exchange is stateless. The client carries forward exactly what's needed between turns: recent message history, the last-referenced entity (for "move it to Monday"), and a pending-disambiguation set (for "the 2pm one" after being shown multiple matches).

**`/execute` is idempotent and staleness-aware.** A double-click or network retry replays the cached result instead of double-creating something; deleting an already-gone item returns a clean "no longer exists" instead of a raw API error. Confirmed empirically: Calendar raises a real 410 on a stale delete; Tasks' delete is quietly idempotent and never does — the handler accounts for both.

**Read → match → confirm is identical for Calendar and Tasks**, via one shared fuzzy-matching resolver (`app/services/resolve.py`), so Tasks never became the less-tested path trailing behind Calendar.

## Setup

### Prerequisites
- Python 3.12+ and [`uv`](https://github.com/astral-sh/uv)
- Node 20+
- A Google Cloud project
- A [Groq](https://console.groq.com) API key

### Google Cloud
1. Enable **Google Calendar API**, **Tasks API**, and **People API**.
2. Google Auth Platform → Audience: **External**, add your own Google account as a **test user**.
3. Data Access → add these scopes:
   - `.../auth/calendar.events`, `.../auth/tasks`, `openid`, `.../auth/userinfo.email`
   - `.../auth/contacts.readonly`, `.../auth/contacts.other.readonly` (for attendee-name lookup)
4. Clients → Create OAuth client (Web application) → add redirect URI `http://localhost:8000/auth/callback` (and your deployed backend's `/auth/callback` if hosting it).

### Backend
```bash
cd backend
uv sync
cp .env.example .env   # fill in GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET, GROQ_API_KEY
uv run uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL, defaults to http://localhost:8000
npm run dev
```

Open http://localhost:3000, log in with Google, start talking to it.

### Tests
```bash
cd backend
uv run pytest
```

## Reliability & AI reasoning

- **Datetime resolution is pure, LLM-free logic** (`app/nlu/datetime_resolver.py`), with 26 unit tests — the component most likely to silently misfire is held to the highest bar, not left to the model. It explicitly handles the "Friday said on a Friday" ambiguity (today, unless that time's already passed, then next week), the "next" vs. bare-weekday distinction, and vague time-of-day defaults ("Monday morning" → 9am).
- **Read → match → confirm** for every update/delete/complete: the agent never lets the LLM invent an event/task ID. It fuzzy-matches the user's description against the real list fetched from Google, and if more than one item plausibly matches, it asks which one — showing the distinguishing date/time, not just the name, since two items can share a title.
- **Disambiguation survives the next turn.** A reply like "the 2pm one" or "the second one" is matched against what was *actually* offered, carried across the stateless turn boundary — including trusting the original request's intent over a short follow-up's own (sometimes unreliable) re-classification.
- **Contact resolution** (`app/services/contacts.py`): a named attendee resolves to an email automatically via Google's People API — checking both saved contacts and Gmail's "Other contacts" (two separate API scopes) — when confidently and unambiguously matched. Falls back to asking for the email only when genuinely unresolved; a deterministic regex safety net also catches cases where the LLM recognizes a name in the title but forgets to flag it as an attendee.
- **Conflict detection**: creating or moving an event checks for time overlaps against the existing calendar and surfaces a warning in the confirm step, without blocking the action — still the user's call.

## Error handling

| Case | Handling |
|---|---|
| Ambiguous request (multiple matches) | Clarify question listing distinguishing candidates by date/time; a follow-up is matched against what was actually offered |
| Missing information (no time, no title, unresolved attendee email) | Clarify question for the specific missing piece — e.g. "what day" vs "what time" are asked separately, not conflated |
| Invalid operation (target doesn't exist) | Clear error message, never a guess |
| Google API failure | Distinguished from "resource gone" (404/410 → friendly "no longer exists") vs. other errors (surfaced plainly) |
| Auth expired mid-session | 401 detected client-side, triggers a clean re-login with a "session expired" notice — not a silent failure |
| Bulk requests ("delete all of them") | Not supported yet; caught before it reaches target resolution and redirected to ask for one specific item, instead of risking the model guessing at an unrelated item |

## Production readiness

- **Deployed**: frontend on Vercel, backend on Railway, both auto-deploying from `master`.
- **Auth**: FastAPI owns the full Google OAuth2 flow and issues a short-lived (45 min) JWT to the client rather than a cross-domain cookie — deliberately avoids SameSite/CORS complexity across two separate hosting domains, at the cost of a bearer token living in browser memory. A conscious tradeoff, not an oversight.
- **Refresh tokens** are stored server-side (SQLite locally; a real production deployment would move this to a managed Postgres instance with encryption at rest — noted explicitly in [Known limitations](#known-limitations), not glossed over).
- **`/execute` is idempotent** (dedupe keyed on a client-generated request ID, not the action's content — so two genuinely-intended identical actions are never conflated) and staleness-aware (see [Architecture](#architecture)).

## Testing

```bash
cd backend
uv run pytest      # 26 passed
```

Automated coverage is deliberately concentrated where it matters most: the **datetime/timezone resolver** — the single component most likely to silently produce a wrong answer that only shows up hours later — has 26 unit tests covering same-day-weekday ambiguity, "next" vs. bare-weekday, explicit-vs-vague time-of-day, and range resolution. The LLM-interpretation layer, disambiguation flow, contact resolution, and Google API wrappers are currently verified through manual/live testing rather than automated tests — an honest gap, not a hidden one, and the next piece to close given more time.

## Known limitations

- **OAuth is in Google's "Testing" publishing status** — full verification for the sensitive scopes here (Calendar, Tasks, Contacts) wasn't feasible in this timeframe. Only accounts added as test users can log in.
- **Voice input**: native Web Speech API (Chrome/Edge) with a Groq Whisper-based record-and-transcribe fallback for Safari/Firefox/mobile browsers that don't have it — the fallback has real upload+transcription latency the native path doesn't, since it's a genuine round trip rather than on-device recognition.
- **Bulk operations** ("delete all of them") aren't supported — the assistant asks for one specific item rather than guessing at multiple.
- **Task due dates are date-only.** This is a Google Tasks API constraint (the time-of-day component is discarded server-side, by Google's own design), not a bug here.
- **Single calendar / single tasklist**: only the `"primary"` Google Calendar and the default (`@default`) Google Tasks list are addressed — no multi-calendar or multi-tasklist support.
- **Token storage** is a local SQLite file, fine for this deployment's scale but not durable against an ephemeral-disk host restart — a real production deployment would move this to managed Postgres (see [Production readiness](#production-readiness)).
- **Automated test coverage** is concentrated on the datetime resolver (see [Testing](#testing)) rather than spread evenly across every module.
- **Sidebar quick-actions**: clicking an event/task in the side panel pre-fills a suggested command in the chat input (still requires explicit confirm) rather than editing directly — the conversational agent is the primary interface, the sidebar is a glance-and-jump-in shortcut into it.

## Project structure

```
backend/
  app/
    agent/
      graph.py          LangGraph nodes: interpret → create / mutate_existing / read / chitchat
      interpret.py       the only LLM call — intent + slot extraction, nothing else
      execute.py         hardened /execute dispatcher — dedupe, act, staleness handling
      schema.py          wire contract (ChatRequest/Response, ProposedAction, Disambiguation)
    nlu/
      datetime_resolver.py   pure-logic relative date/time resolution (26 tests)
      fuzzy_match.py         shared scoring used by both entity matching and contacts
    services/
      calendar.py / tasks.py   Google API CRUD wrappers
      resolve.py               shared read → match → confirm, used by both services
      contacts.py              People API lookup for attendee-name → email resolution
      transcribe.py            Groq Whisper fallback transcription
    auth.py              Google OAuth2 flow + JWT issuance
    google_clients.py    per-user authenticated Calendar/Tasks/People clients
    token_store.py        refresh-token persistence (SQLite)
  tests/
    test_datetime_resolver.py
frontend/
  src/
    app/page.tsx          chat UI, confirm/cancel, side panel
    lib/
      chat.ts              typed API client for /chat, /execute, /transcribe
      speech.ts             voice input: native SpeechRecognition + MediaRecorder fallback
      auth.ts               session-token storage
```

## Tech stack

**Backend:** FastAPI, LangGraph, Groq (`llama-3.1-8b-instant` for reasoning, `whisper-large-v3-turbo` for transcription), `google-api-python-client`, SQLite (dev token store), pytest.
**Frontend:** Next.js 16 (App Router), TypeScript, Tailwind CSS, Web Speech API.
**Deployment:** Vercel (frontend), Railway (backend).
