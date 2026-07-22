import { clearToken, getToken } from "./auth";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Distinguishes an expired/invalid session from any other API failure, so
// the UI can trigger a clean re-login instead of showing a raw error
// (PLAN.md §7: "auth expired -> frontend triggers re-login, not a silent failure").
export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

export async function apiFetch(path: string, init: RequestInit = {}) {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    throw new SessionExpiredError();
  }
  return res;
}
