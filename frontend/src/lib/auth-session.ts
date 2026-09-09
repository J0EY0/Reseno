export const AUTH_SESSION_KEY = "reseno-auth-session";
export const AUTH_REFRESH_LOCK_NAME = "reseno-auth-refresh";
const INVALIDATED_TOKEN_CACHE_KEY = "reseno-invalidated-jwts";
const INVALIDATED_TOKEN_TTL_MS = 4 * 60 * 60 * 1000;

interface AuthSession {
  username: string;
  accessToken: string;
  expiresAt: string;
}

type InvalidatedTokenCache = Record<string, number>;

let invalidatedTokenCache: InvalidatedTokenCache | undefined;
let cachedSessionRaw: string | null = null;
let cachedSession: Partial<AuthSession> | null = null;

function readInvalidatedTokenCache(): InvalidatedTokenCache {
  if (invalidatedTokenCache) {
    return invalidatedTokenCache;
  }

  invalidatedTokenCache = {};
  if (typeof window === "undefined") {
    return invalidatedTokenCache;
  }

  try {
    const raw = window.sessionStorage.getItem(INVALIDATED_TOKEN_CACHE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      invalidatedTokenCache = Object.fromEntries(
        Object.entries(parsed).filter(
          ([, expiresAt]) =>
            typeof expiresAt === "number" && expiresAt > Date.now(),
        ),
      );
    }
  } catch {
    return invalidatedTokenCache;
  }

  return invalidatedTokenCache;
}

export function recordInvalidatedToken(token: string) {
  if (!token) {
    return;
  }

  const now = Date.now();
  invalidatedTokenCache = Object.fromEntries(
    Object.entries(readInvalidatedTokenCache()).filter(
      ([, expiresAt]) => expiresAt > now,
    ),
  );
  invalidatedTokenCache[token] = now + INVALIDATED_TOKEN_TTL_MS;

  if (typeof window === "undefined") {
    return;
  }

  try {
    window.sessionStorage.setItem(
      INVALIDATED_TOKEN_CACHE_KEY,
      JSON.stringify(invalidatedTokenCache),
    );
  } catch {
    return;
  }
}

export function isTokenLocallyInvalidated(token: string) {
  if (!token) {
    return false;
  }

  return readInvalidatedTokenCache()[token] > Date.now();
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_KEY);
    if (raw !== cachedSessionRaw) {
      cachedSession = raw ? (JSON.parse(raw) as Partial<AuthSession>) : null;
      cachedSessionRaw = raw;
    }
    const parsed = cachedSession;
    const expiresAt = Date.parse(parsed?.expiresAt ?? "");

    if (
      !parsed?.username ||
      !parsed.accessToken ||
      !parsed.expiresAt ||
      Number.isNaN(expiresAt) ||
      expiresAt <= Date.now() ||
      isTokenLocallyInvalidated(parsed.accessToken)
    ) {
      return null;
    }

    return parsed.accessToken;
  } catch {
    return null;
  }
}

export function saveAuthSession(
  username: string,
  accessToken: string,
  expiresAt: string,
) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    AUTH_SESSION_KEY,
    JSON.stringify({
      username: username.trim(),
      accessToken,
      expiresAt,
    } satisfies AuthSession),
  );
}

export function clearAuthSession() {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.removeItem(AUTH_SESSION_KEY);
}

export function loadAuthSession() {
  return Boolean(getAccessToken());
}
