export const AUTH_SESSION_KEY = 'resumate-auth-session'
export const AUTH_REFRESH_LOCK_NAME = 'resumate-auth-refresh'
const INVALIDATED_TOKEN_CACHE_KEY = 'resumate-invalidated-jwts'
const INVALIDATED_TOKEN_TTL_MS = 4 * 60 * 60 * 1000

export interface AuthSession {
  username: string
  authenticatedAt: string
  accessToken: string
  expiresAt: string
}

type InvalidatedTokenCache = Record<string, number>

function readInvalidatedTokenCache(): InvalidatedTokenCache {
  if (typeof window === 'undefined') {
    return {}
  }

  try {
    const raw = window.sessionStorage.getItem(INVALIDATED_TOKEN_CACHE_KEY)
    return raw ? (JSON.parse(raw) as InvalidatedTokenCache) : {}
  } catch {
    return {}
  }
}

function writeInvalidatedTokenCache(cache: InvalidatedTokenCache) {
  if (typeof window === 'undefined') {
    return
  }

  window.sessionStorage.setItem(
    INVALIDATED_TOKEN_CACHE_KEY,
    JSON.stringify(cache),
  )
}

export function pruneInvalidatedTokenCache() {
  const now = Date.now()
  const cache = readInvalidatedTokenCache()
  const nextCache = Object.fromEntries(
    Object.entries(cache).filter(([, expiresAt]) => expiresAt > now),
  )

  writeInvalidatedTokenCache(nextCache)
  return nextCache
}

export function recordInvalidatedToken(token: string) {
  if (!token) {
    return
  }

  const cache = pruneInvalidatedTokenCache()
  cache[token] = Date.now() + INVALIDATED_TOKEN_TTL_MS
  writeInvalidatedTokenCache(cache)
}

export function isTokenLocallyInvalidated(token: string) {
  if (!token) {
    return false
  }

  return token in pruneInvalidatedTokenCache()
}

export function getAuthSession(): AuthSession | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_KEY)
    const parsed = raw ? (JSON.parse(raw) as Partial<AuthSession>) : null

    if (
      !parsed?.username ||
      !parsed.accessToken ||
      !parsed.expiresAt ||
      Number.isNaN(Date.parse(parsed.expiresAt)) ||
      Date.parse(parsed.expiresAt) <= Date.now() ||
      isTokenLocallyInvalidated(parsed.accessToken)
    ) {
      return null
    }

    return {
      username: parsed.username,
      authenticatedAt: parsed.authenticatedAt ?? new Date().toISOString(),
      accessToken: parsed.accessToken,
      expiresAt: parsed.expiresAt,
    }
  } catch {
    return null
  }
}

export function getAccessToken() {
  return getAuthSession()?.accessToken ?? null
}

export function saveAuthSession(
  username: string,
  accessToken: string,
  expiresAt: string,
) {
  if (typeof window === 'undefined') {
    return
  }

  window.localStorage.setItem(
    AUTH_SESSION_KEY,
    JSON.stringify({
      username: username.trim(),
      authenticatedAt: new Date().toISOString(),
      accessToken,
      expiresAt,
    } satisfies AuthSession),
  )
}

export function clearAuthSession() {
  if (typeof window === 'undefined') {
    return
  }

  window.localStorage.removeItem(AUTH_SESSION_KEY)
}

export function loadAuthSession() {
  return Boolean(getAuthSession())
}
