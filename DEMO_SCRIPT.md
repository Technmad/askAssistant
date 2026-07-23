# Demo video script (~7-8 min)

**Before recording**: clean up leftover test events/tasks (the duplicate "Meeting with Asmita"/"Meeting with Deepak" ones) so the demo calendar looks realistic, not cluttered. Have the production URL open, logged out, so the login flow is visible.

## 1. Intro (15s)
"This is an AI personal assistant for Google Calendar and Tasks — natural language, voice or text, built with FastAPI, LangGraph, and Groq on the backend, Next.js on the frontend."

## 2. Login (20s)
Show the landing page, click "Continue with Google", approve consent. Land on the chat UI.

## 3. Text command + attendee resolution (60s)
Type: **"Schedule a meeting with [a real contact] tomorrow at 3pm"**
- Show it either (a) auto-resolving their email via Contacts, or (b) asking for the email if not a saved contact — either is a good demo of reliability.
- Confirm it. Point out the side panel updating with the new event.

## 4. Voice command (45s)
Click the mic, speak: **"What's on my calendar this week?"**
- Shows voice input working and a read-only query (no confirm needed).

## 5. Ambiguous / missing info handled gracefully (60s)
Type: **"Schedule a meeting tomorrow"** (deliberately no time)
- Shows it asks "What time should this be?" instead of guessing.
- Answer it, let it propose, confirm.

## 6. Move + conflict detection (45s)
Type: **"Move my [meeting] to [a time that overlaps something else]"**
- Point out the "(overlaps with X)" warning in the confirm message — still lets you proceed, just informs you.

## 7. Tasks: create, complete, reopen (60s)
- **"Create a task to submit the monthly report next Monday"** → confirm.
- **"Mark [task] as completed"** → confirm.
- **"Unmark it"** (no name at all) → shows it correctly reopens the *same* task using conversation context, not a random one.

## 8. Delete with disambiguation (60s)
If you have two similarly-named events: **"Delete [event name]"** → it lists both with distinguishing times → reply **"the 2pm one"** → confirms the specific one → delete.
- This is a good one to narrate explicitly: "notice it asks which one, and I can answer by the time it showed me, not just the name."

## 9. One graceful failure (30s)
Pick something to show a clean failure state — e.g. try to delete something that no longer exists (delete the same thing twice quickly), or just let your session sit past 45 minutes and show the "session expired, please log in again" screen instead of a crash.

## 10. Wrap-up (20s)
"Every create, update, delete, and complete goes through an explicit confirm step before anything touches your real calendar. The architecture, known limitations, and setup instructions are all in the README."

---

**Total: ~4-5 min of core content** — comfortably under 10 min even with narration pauses and re-takes. If you have time left, add a quick shot of the code (agent/graph.py's node structure, or the datetime resolver tests passing) to show the engineering underneath, not just the UI.
