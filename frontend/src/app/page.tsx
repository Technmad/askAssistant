"use client";

import { useEffect, useRef, useState } from "react";
import {
  CalendarEvent,
  ChatResponse,
  HistoryTurn,
  ProposedAction,
  ReferencedEntity,
  Task,
  executeAction,
  fetchOpenTasks,
  fetchUpcomingEvents,
  sendChat,
} from "@/lib/chat";
import { API_BASE_URL, SessionExpiredError } from "@/lib/api";
import { clearToken, getToken } from "@/lib/auth";
import { cancelSpeech, speak, useSpeechRecognition } from "@/lib/speech";
import {
  CalendarIcon,
  CheckIcon,
  CheckSquareIcon,
  GoogleIcon,
  LogOutIcon,
  MicIcon,
  PanelIcon,
  SendIcon,
  SparklesIcon,
  VolumeIcon,
  VolumeOffIcon,
  XIcon,
} from "@/components/icons";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  isError?: boolean;
  proposedAction?: ProposedAction;
  resolution?: "confirmed" | "cancelled";
};

const WELCOME: Message = {
  id: "welcome",
  role: "assistant",
  content:
    "Hi! I can manage your Google Calendar and Tasks -- try \"schedule a meeting tomorrow at 3pm\", " +
    "\"what's on my calendar this week\", or \"create a task to submit the report next Monday\".",
};

function newId() {
  return typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function formatWhen(iso: string | null | undefined) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function Home() {
  const [token, setTokenState] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [lastReferencedEntity, setLastReferencedEntity] = useState<ReferencedEntity | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [muted, setMuted] = useState(false);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setTokenState(getToken());
  }, []);

  useEffect(() => {
    if (token) refreshSidePanel();
  }, [token]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  function handleSessionExpired() {
    cancelSpeech();
    setSessionExpired(true);
    setTokenState(null);
    setMessages([WELCOME]);
    setLastReferencedEntity(null);
  }

  async function refreshSidePanel() {
    try {
      const [ev, tk] = await Promise.all([fetchUpcomingEvents(), fetchOpenTasks()]);
      setEvents(ev);
      setTasks(tk);
    } catch (err) {
      if (err instanceof SessionExpiredError) handleSessionExpired();
    }
  }

  function speakIfEnabled(text: string) {
    // Multi-line results (calendar/task lists) read awkwardly aloud --
    // only speak short, single-line responses (clarify/propose/result confirmations).
    if (!muted && !text.includes("\n")) speak(text);
  }

  async function handleSend(rawText: string) {
    const text = rawText.trim();
    if (!text || sending) return;

    const userMessage: Message = { id: newId(), role: "user", content: text };
    const history: HistoryTurn[] = [...messages, userMessage]
      .filter((m) => m.id !== "welcome")
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setSending(true);

    try {
      const response = await sendChat(text, history, lastReferencedEntity);
      applyResponse(response);
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        handleSessionExpired();
        return;
      }
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "assistant", content: `Something went wrong: ${err}`, isError: true },
      ]);
    } finally {
      setSending(false);
    }
  }

  function applyResponse(response: ChatResponse) {
    if (response.referenced_entity) setLastReferencedEntity(response.referenced_entity);
    setMessages((prev) => [
      ...prev,
      {
        id: newId(),
        role: "assistant",
        content: response.message,
        isError: response.type === "error",
        proposedAction: response.proposed_action ?? undefined,
      },
    ]);
    speakIfEnabled(response.message);
  }

  async function handleConfirm(message: Message) {
    if (!message.proposedAction) return;
    setMessages((prev) => prev.map((m) => (m.id === message.id ? { ...m, resolution: "confirmed" as const } : m)));
    setSending(true);
    try {
      const result = await executeAction(message.proposedAction);
      applyResponse(result);
      if (result.type === "result") refreshSidePanel();
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        handleSessionExpired();
        return;
      }
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "assistant", content: `Couldn't complete that: ${err}`, isError: true },
      ]);
    } finally {
      setSending(false);
    }
  }

  function handleCancel(message: Message) {
    setMessages((prev) => [
      ...prev.map((m) => (m.id === message.id ? { ...m, resolution: "cancelled" as const } : m)),
      { id: newId(), role: "assistant", content: "Cancelled." },
    ]);
  }

  const {
    supported: voiceSupported,
    listening,
    start: startListening,
    stop: stopListening,
  } = useSpeechRecognition((transcript) => {
    handleSend(transcript);
  });

  function toggleListening() {
    if (listening) stopListening();
    else startListening();
  }

  function logout() {
    cancelSpeech();
    clearToken();
    setSessionExpired(false);
    setTokenState(null);
    setMessages([WELCOME]);
    setLastReferencedEntity(null);
  }

  if (!token) {
    return (
      <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-linear-to-br from-indigo-50 via-white to-violet-50 px-6 dark:from-zinc-950 dark:via-zinc-950 dark:to-indigo-950">
        <div className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 animate-drift rounded-full bg-indigo-300/30 blur-3xl dark:bg-indigo-700/20" />
        <div className="pointer-events-none absolute -bottom-24 -right-24 h-96 w-96 animate-drift rounded-full bg-violet-300/30 blur-3xl dark:bg-violet-700/20 [animation-delay:6s]" />

        <div className="relative flex w-full max-w-md flex-col items-center gap-6 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-linear-to-br from-indigo-600 to-violet-600 text-white shadow-lg shadow-indigo-600/30">
            <SparklesIcon className="h-8 w-8" />
          </div>

          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-white">Assistant</h1>
            <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
              Manage your Google Calendar and Tasks with natural language -- voice or text.
            </p>
          </div>

          {sessionExpired && (
            <div className="w-full rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              Your session expired -- please log in again.
            </div>
          )}

          <div className="grid w-full grid-cols-3 gap-2 text-xs">
            {[
              { icon: <MicIcon className="h-4 w-4" />, label: "Voice or text" },
              { icon: <CalendarIcon className="h-4 w-4" />, label: "Smart scheduling" },
              { icon: <CheckSquareIcon className="h-4 w-4" />, label: "Always confirms" },
            ].map((f) => (
              <div
                key={f.label}
                className="flex flex-col items-center gap-1.5 rounded-xl border border-zinc-200 bg-white/70 px-2 py-3 text-zinc-600 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/60 dark:text-zinc-300"
              >
                <span className="text-indigo-600 dark:text-indigo-400">{f.icon}</span>
                {f.label}
              </div>
            ))}
          </div>

          <a
            href={`${API_BASE_URL}/auth/login`}
            className="flex items-center gap-3 rounded-full bg-white px-6 py-3 font-medium text-zinc-800 shadow-lg shadow-zinc-900/10 ring-1 ring-zinc-200 transition hover:shadow-xl active:scale-[0.98] dark:bg-zinc-900 dark:text-white dark:ring-zinc-700"
          >
            <GoogleIcon className="h-5 w-5" />
            Continue with Google
          </a>
          <p className="text-xs text-zinc-400 dark:text-zinc-600">
            Connects securely to your Google Calendar and Tasks.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="flex h-screen flex-col bg-slate-50 dark:bg-zinc-950 md:flex-row">
      <section className="flex min-h-0 flex-1 flex-col border-zinc-200 dark:border-zinc-800 md:border-r">
        <header className="flex items-center justify-between border-b border-zinc-200 bg-white/80 px-4 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-linear-to-br from-indigo-600 to-violet-600 text-white">
              <SparklesIcon className="h-4 w-4" />
            </div>
            <h1 className="text-base font-semibold text-zinc-900 dark:text-white">Assistant</h1>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              className="rounded-full p-2 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 md:hidden dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
              title={sidebarOpen ? "Hide events/tasks" : "Show events/tasks"}
            >
              <PanelIcon className="h-4 w-4" />
            </button>
            <button
              onClick={() => setMuted((m) => !m)}
              className="rounded-full p-2 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
              title={muted ? "Unmute replies" : "Mute replies"}
            >
              {muted ? <VolumeOffIcon className="h-4 w-4" /> : <VolumeIcon className="h-4 w-4" />}
            </button>
            <button
              onClick={logout}
              className="rounded-full p-2 text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-100"
              title="Log out"
            >
              <LogOutIcon className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4">
          {messages.map((m) => (
            <div
              key={m.id}
              className={`mb-3 flex animate-fade-in-up ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm shadow-sm ${
                  m.role === "user"
                    ? "rounded-br-md bg-linear-to-br from-indigo-600 to-violet-600 text-white"
                    : m.isError
                    ? "rounded-bl-md border border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                    : "rounded-bl-md border border-zinc-200 bg-white text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100"
                }`}
              >
                {m.content}
                {m.proposedAction && !m.resolution && (
                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={() => handleConfirm(m)}
                      className="flex items-center gap-1 rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-500 active:scale-95"
                    >
                      <CheckIcon className="h-3.5 w-3.5" />
                      Confirm
                    </button>
                    <button
                      onClick={() => handleCancel(m)}
                      className="flex items-center gap-1 rounded-full bg-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-700 transition hover:bg-zinc-300 active:scale-95 dark:bg-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-600"
                    >
                      <XIcon className="h-3.5 w-3.5" />
                      Cancel
                    </button>
                  </div>
                )}
                {m.resolution && (
                  // proposedAction/resolution only ever occur on assistant messages
                  // (see applyResponse/handleConfirm/handleCancel), so no user-bubble case to handle.
                  <div
                    className={`mt-1.5 flex items-center gap-1 text-xs font-medium ${
                      m.resolution === "confirmed"
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-zinc-400"
                    }`}
                  >
                    {m.resolution === "confirmed" ? <CheckIcon className="h-3 w-3" /> : <XIcon className="h-3 w-3" />}
                    {m.resolution === "confirmed" ? "Confirmed" : "Cancelled"}
                  </div>
                )}
              </div>
            </div>
          ))}
          {sending && (
            <div className="mb-3 flex justify-start">
              <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-md border border-zinc-200 bg-white px-4 py-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
                {[0, 1, 2].map((i) => (
                  <span
                    key={i}
                    className="h-1.5 w-1.5 animate-bounce-dot rounded-full bg-zinc-400"
                    style={{ animationDelay: `${i * 0.15}s` }}
                  />
                ))}
              </div>
            </div>
          )}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend(input);
          }}
          className="flex items-center gap-2 border-t border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950"
        >
          <div className="flex flex-1 items-center rounded-full border border-zinc-300 bg-zinc-50 px-4 py-2 transition focus-within:border-indigo-400 focus-within:ring-2 focus-within:ring-indigo-100 dark:border-zinc-700 dark:bg-zinc-900 dark:focus-within:ring-indigo-950">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask me to schedule, move, or check something..."
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-zinc-400"
            />
          </div>
          {voiceSupported && (
            <button
              type="button"
              onClick={toggleListening}
              className={`relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition ${
                listening
                  ? "animate-pulse-ring bg-red-500 text-white"
                  : "bg-zinc-100 text-zinc-500 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
              }`}
              title={listening ? "Stop listening" : "Voice input"}
            >
              <MicIcon className="h-4 w-4" />
            </button>
          )}
          <button
            type="submit"
            disabled={sending}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-linear-to-br from-indigo-600 to-violet-600 text-white transition hover:shadow-md active:scale-95 disabled:opacity-40"
            title="Send"
          >
            <SendIcon className="h-4 w-4" />
          </button>
        </form>
      </section>

      <aside
        className={`${sidebarOpen ? "block" : "hidden"} w-full shrink-0 overflow-y-auto bg-white p-4 md:block md:w-72 md:max-h-full dark:bg-zinc-950`}
      >
        <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-400">
          <CalendarIcon className="h-3.5 w-3.5" />
          Upcoming events
        </div>
        <ul className="mb-6 space-y-1.5">
          {events.length === 0 && <li className="text-sm text-zinc-400">Nothing upcoming.</li>}
          {events.map((e) => (
            <li
              key={e.id}
              className="rounded-xl border-l-4 border-indigo-500 bg-zinc-50 p-2.5 text-sm shadow-sm dark:bg-zinc-900"
            >
              <div className="font-medium text-zinc-800 dark:text-zinc-100">{e.summary}</div>
              <div className="text-xs text-zinc-400">{formatWhen(e.start)}</div>
            </li>
          ))}
        </ul>

        <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-zinc-400">
          <CheckSquareIcon className="h-3.5 w-3.5" />
          Open tasks
        </div>
        <ul className="space-y-1.5">
          {tasks.length === 0 && <li className="text-sm text-zinc-400">No open tasks.</li>}
          {tasks.map((t) => (
            <li
              key={t.id}
              className="rounded-xl border-l-4 border-violet-500 bg-zinc-50 p-2.5 text-sm shadow-sm dark:bg-zinc-900"
            >
              <div className="font-medium text-zinc-800 dark:text-zinc-100">{t.title}</div>
              {t.due && <div className="text-xs text-zinc-400">due {formatWhen(t.due)}</div>}
            </li>
          ))}
        </ul>
      </aside>
    </main>
  );
}
