"use client";

import { useEffect, useState } from "react";
import { apiFetch, API_BASE_URL } from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";

type CalendarEvent = { id: string; summary: string; start: string };

export default function Home() {
  const [token, setTokenState] = useState<string | null>(null);
  const [events, setEvents] = useState<CalendarEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTokenState(getToken());
  }, []);

  async function loadEvents() {
    setError(null);
    setEvents(null);
    const res = await apiFetch("/calendar/events");
    if (!res.ok) {
      setError(`${res.status}: ${await res.text()}`);
      return;
    }
    const data = await res.json();
    setEvents(data.events);
  }

  function logout() {
    clearToken();
    setTokenState(null);
    setEvents(null);
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 bg-zinc-50 p-8 font-sans dark:bg-black">
      <h1 className="text-2xl font-semibold">AI Personal Assistant — auth spike</h1>

      {!token ? (
        <a
          href={`${API_BASE_URL}/auth/login`}
          className="rounded-full bg-black px-6 py-3 text-white dark:bg-white dark:text-black"
        >
          Login with Google
        </a>
      ) : (
        <div className="flex flex-col items-center gap-4">
          <p className="text-sm text-zinc-500">Signed in — session token present.</p>
          <button
            onClick={loadEvents}
            className="rounded-full bg-black px-6 py-3 text-white dark:bg-white dark:text-black"
          >
            Load upcoming Calendar events
          </button>
          <button onClick={logout} className="text-sm underline text-zinc-500">
            Log out
          </button>
          {error && <p className="text-red-600">{error}</p>}
          {events && (
            <ul className="w-full max-w-md text-sm">
              {events.length === 0 && <li>No upcoming events found.</li>}
              {events.map((e) => (
                <li key={e.id} className="border-b py-2">
                  {e.summary} — {e.start}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </main>
  );
}
