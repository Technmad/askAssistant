# AI Personal Assistant — Google Calendar & Tasks

A natural-language assistant for Google Calendar and Google Tasks, by voice or text. Built for the callkaro.ai take-home assignment.

**Live app:** https://ask-assistant-three.vercel.app
**Backend API:** https://askassistant-production.up.railway.app
**Demo video:** _link goes here_
**Source:** https://github.com/Technmad/askAssistant

> Note on access: Google's OAuth consent screen for this project is in **Testing** publishing status (see [Known limitations](#known-limitations)). If you can't log in, that's why — watch the demo video, or ask to be added as a test user.

## What it does

Type or speak things like:

- "Schedule a meeting with John tomorrow at 3pm"
- "What's on my calendar this week?"
- "Move my Friday meeting to Monday morning"
- "Create a task to submit the report next Monday"
- "Mark my grocery task as completed"
- "Delete my dentist appointment"

Every create/update/delete/complete is **proposed first** and only executes after an explicit confirm — nothing happens silently.

## Architecture

```
Next.js (Vercel)                       FastAPI (Railway)                     Google APIs
─────────────────                       ──────────────────                    ───────────
Chat UI (text + voice)      ───────▶    /auth/login, /auth/callback  ──────▶ OAuth2
 • Web Speech API (native)               (issues a short-lived JWT)
 • Whisper fallback (Safari/Firefox)
                             ───────▶    /chat  (LangGraph agent)
                             ◀───────      • Groq LLM: intent + slot extraction ONLY
Confirm / Cancel UI                        • deterministic code: dates, entity
                             ───────▶        matching, conflict checks, contacts
                                          /execute (dedupe + act, idempotent)
                                            │
                                            ├─ Calendar API (CRUD)
                                            ├─ Tasks API (CRUD)
                                            ├─ People API (contact lookup)
                                            └─ token store (SQLite locally)
```

### Why it's built this way

**The LLM only extracts language — it never decides anything reliability-critical.** Groq's `llama-3.1-8b-instant` reads the user's message and pulls out an intent plus raw slots (a title, a phrase like "tomorrow 3pm", who to invite). It never resolves a date, never invents an entity ID, never decides a scheduling conflict. All of that is deterministic Python, independently unit-tested from the LLM. This split is the main answer to "how is this reliable" — the parts most likely to silently misfire never touch the model.

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

- Deployed: frontend on Vercel, backend on Railway, both auto-deploying from `master`.
- Auth: FastAPI owns the full Google OAuth2 flow and issues a short-lived (45 min) JWT to the client rather than a cross-domain cookie — deliberately avoids SameSite/CORS complexity across two separate hosting domains, at the cost of a bearer token living in browser memory. A conscious tradeoff, not an oversight.
- Refresh tokens are stored server-side (SQLite locally; a real production deployment would move this to a managed Postgres instance with encryption at rest).
- `/execute` is idempotent (dedupe keyed on a client-generated request ID, not the action's content — so two genuinely-intended identical actions are never conflated) and staleness-aware (see above).

## Known limitations

- **OAuth is in Google's "Testing" publishing status** — full verification for the sensitive scopes here (Calendar, Tasks, Contacts) wasn't feasible in this timeframe. Only accounts added as test users can log in.
- **Voice input**: native Web Speech API (Chrome/Edge) with a Groq Whisper-based record-and-transcribe fallback for Safari/Firefox/mobile browsers that don't have it.
- **Bulk operations** ("delete all of them") aren't supported — the assistant asks for one specific item rather than guessing at multiple.
- **Task due dates are date-only.** This is a Google Tasks API constraint (the time-of-day component is discarded server-side, by Google's own design), not a bug here.
- **Sidebar quick-actions**: clicking an event/task in the side panel pre-fills a suggested command in the chat input (still requires explicit confirm) rather than editing directly — the conversational agent is the primary interface, the sidebar is a glance-and-jump-in shortcut into it.

## Tech stack

**Backend:** FastAPI, LangGraph, Groq (`llama-3.1-8b-instant` + `whisper-large-v3-turbo`), `google-api-python-client`, SQLite (dev token store), pytest.
**Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, Web Speech API.
