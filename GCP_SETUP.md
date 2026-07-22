# Google Cloud Console Setup Checklist

Do this before any backend code. All of it is manual (console clicks) — nothing here is scriptable from the CLI reliably, so work through it in order.

## 1. Create the project
- [ ] console.cloud.google.com → project dropdown (top left) → **New Project**
- [ ] Name it (e.g. `callkaro-assistant`) → **Create**
- [ ] Select it in the project dropdown so it's the active project for every step below

## 2. Enable the two APIs
- [ ] **APIs & Services → Library** → search `Google Calendar API` → **Enable**
- [ ] Same page → search `Tasks API` (Google Tasks API) → **Enable**

## 3. Google Auth Platform (formerly "OAuth consent screen" — Google rebranded/restructured this into tabs)
- [ ] **APIs & Services → Google Auth Platform** → **Get started**
- [ ] **App information**: app name, your email as User support email → Next
- [ ] **Audience**: **External** (Internal requires a Workspace org) → Next
- [ ] **Contact information**: your email → Next
- [ ] **Finish**: check the Google API Services User Data Policy box → Continue/Create
- [ ] On the resulting dashboard, **Audience** tab → confirm **Publishing status: Testing**, add your Google account email under **Test users** (add any evaluator's email here too if they'll log in live rather than only watch the demo video)
- [ ] **Data Access** tab → **Add or remove scopes** → add exactly these (least-privilege, matches what the assistant actually does):
  - `https://www.googleapis.com/auth/calendar.events` — create/read/update/delete events (not full calendar-list management, which you don't need)
  - `https://www.googleapis.com/auth/tasks` — full task CRUD (no more-restrictive scope exists for write access)
  - `openid` + `https://www.googleapis.com/auth/userinfo.email` — identifies the user for your session JWT
- [ ] Do not click "Publish App" anywhere in this flow — that triggers Google's verification review for sensitive scopes, which is not achievable in this timeframe.

## 4. Create OAuth client credentials
- [ ] **Google Auth Platform → Clients** tab → **Create client**
- [ ] Application type: **Web application**
- [ ] Name: e.g. `assistant-backend`
- [ ] Authorized redirect URIs — add now:
  - `http://localhost:8000/auth/callback` (local dev)
  - *(leave room to add the production one after work session 1's deploy step — see §6 below)*
- [ ] Create → copy the **Client ID** and **Client Secret** immediately (secret is only shown once in full)

## 5. Store as env vars (never commit these)
```
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
JWT_SECRET=<generate a random 32+ byte string>
```

## 6. After the skeleton backend is deployed (Railway/Fly)
- [ ] Back to **Credentials → edit the OAuth client** → add the production redirect URI, e.g. `https://<your-app>.up.railway.app/auth/callback`
- [ ] Update `GOOGLE_REDIRECT_URI` in the hosting platform's env vars to match the environment (local vs prod uses a different value — don't hardcode one)

## Known limitations to carry into the README
- **Testing-mode refresh tokens expire after 7 days** (Google's rule for unverified apps requesting sensitive scopes). Irrelevant for a 24h build, but note it explicitly so it doesn't read as an oversight.
- **Only test users added in §3 can complete login** — anyone else hits Google's "app not verified" block screen. This is why the demo video matters: it's the fallback for anyone not added as a test user.
