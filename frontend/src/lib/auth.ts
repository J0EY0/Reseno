import { apiRoutes, requestApi } from "@/lib/api-client";
import {
  clearAuthSession,
  getAccessToken,
  isAuthRequired,
  loadAuthSession,
  recordInvalidatedToken,
  saveAuthSession,
} from "@/lib/auth-session";

export interface AuthTokenPayload {
  username: string
  accessToken: string
  expiresAt: string
  tokenType: string
}

export interface AuthPasswordUpdatePayload {
  currentPassword: string
  newPassword: string
  confirmPassword: string
}

export async function loginWithCredentials(username: string, password: string) {
  const result = await requestApi<AuthTokenPayload>(apiRoutes.authLogin, {
    auth: false,
    body: {
      username: username.trim(),
      password,
    },
    method: 'POST',
  })

  saveAuthSession(result.username, result.accessToken, result.expiresAt)
  return result.username
}

export async function refreshAuthSession() {
  const previousToken = getAccessToken()
  if (!previousToken) {
    clearAuthSession()
    return false
  }

  const result = await requestApi<AuthTokenPayload>(apiRoutes.authRefresh, {
    body: {},
    method: 'POST',
  })

  recordInvalidatedToken(previousToken)
  saveAuthSession(result.username, result.accessToken, result.expiresAt)
  return true
}

export async function updateAuthPassword(payload: AuthPasswordUpdatePayload) {
  const previousToken = getAccessToken()
  const result = await requestApi<{ username: string; updated: boolean }>(
    apiRoutes.authPassword,
    {
      body: payload,
      method: 'POST',
    },
  )

  if (previousToken) {
    recordInvalidatedToken(previousToken)
  }
  clearAuthSession()

  return result
}

export { clearAuthSession, isAuthRequired, loadAuthSession, saveAuthSession }
