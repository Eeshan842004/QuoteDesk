// The admin token is a per-viewer convenience kept in this browser only (never sent anywhere but our API).
const KEY = "quotedesk-admin-token";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function setAdminToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(KEY, token);
    else window.localStorage.removeItem(KEY);
    window.dispatchEvent(new Event("quotedesk-admin"));
  } catch {}
}
