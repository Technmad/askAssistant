import { apiFetch } from "./api";

export type HistoryTurn = { role: "user" | "assistant"; content: string };

export type ReferencedEntity = { type: "event" | "task"; id: string; summary: string };

export type DisambiguationOption = { id: string; name: string; label: string; when?: string | null };
export type Disambiguation = { entity_type: "event" | "task"; intent: string; options: DisambiguationOption[] };

export type ProposedAction = {
  request_id: string;
  action:
    | "calendar.create"
    | "calendar.update"
    | "calendar.delete"
    | "task.create"
    | "task.update"
    | "task.complete"
    | "task.reopen"
    | "task.delete";
  entity_id: string | null;
  params: Record<string, unknown>;
};

export type ChatResponse = {
  type: "clarify" | "propose" | "result" | "error";
  message: string;
  proposed_action?: ProposedAction | null;
  referenced_entity?: ReferencedEntity | null;
  disambiguation?: Disambiguation | null;
};

export type CalendarEvent = { id: string; summary: string; start: string; end?: string };
export type Task = { id: string; title: string; due: string | null; status: string };

// Bounded to the last few turns -- full-transcript stuffing costs tokens
// for no benefit and lets stale context confuse slot-filling.
const MAX_HISTORY_TURNS = 8;

export function boundedHistory(turns: HistoryTurn[]): HistoryTurn[] {
  return turns.slice(-MAX_HISTORY_TURNS);
}

export async function sendChat(
  message: string,
  recentHistory: HistoryTurn[],
  lastReferencedEntity: ReferencedEntity | null,
  pendingDisambiguation: Disambiguation | null
): Promise<ChatResponse> {
  const now = new Date();
  const localIso = new Date(now.getTime() - now.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 19); // naive local wall-clock, no trailing Z/offset -- matches datetime.fromisoformat() server-side

  const res = await apiFetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      recent_history: boundedHistory(recentHistory),
      last_referenced_entity: lastReferencedEntity,
      pending_disambiguation: pendingDisambiguation,
      now: localIso,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function executeAction(proposedAction: ProposedAction): Promise<ChatResponse> {
  const res = await apiFetch("/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      proposed_action: proposedAction,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchUpcomingEvents(): Promise<CalendarEvent[]> {
  const res = await apiFetch("/calendar/events");
  if (!res.ok) return [];
  const data = await res.json();
  return data.events;
}

export async function fetchOpenTasks(): Promise<Task[]> {
  const res = await apiFetch("/tasks/open");
  if (!res.ok) return [];
  const data = await res.json();
  return data.tasks;
}

export async function transcribeAudio(audio: Blob, filename: string): Promise<string> {
  const form = new FormData();
  form.append("audio", audio, filename);
  const res = await apiFetch("/transcribe", { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.text;
}
