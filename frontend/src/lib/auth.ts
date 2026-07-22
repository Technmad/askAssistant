const TOKEN_KEY = "assistant_jwt";

// sessionStorage, not localStorage: token is short-lived (see backend
// JWT_TTL) and this keeps exposure bounded to the tab's lifetime.
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.sessionStorage.removeItem(TOKEN_KEY);
}
