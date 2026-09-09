import { withAuthSessionLock } from "@/lib/auth-environment";
import { apiRoutes, requestApi } from "@/lib/api-client";
import {
  AUTH_SESSION_KEY,
  clearAuthSession,
  getAccessToken,
  loadAuthSession,
  recordInvalidatedToken,
  saveAuthSession,
} from "@/lib/auth-session";

export interface AuthTokenPayload {
  username: string;
  accessToken: string;
  expiresAt: string;
  tokenType: string;
}

interface AuthSetupStatusPayload {
  setupRequired: boolean;
  githubLoginAvailable: boolean;
}

interface AuthSetupPayload {
  username: string;
  password: string;
  confirmPassword: string;
}

interface AuthUsernameUpdatePayload {
  currentPassword: string;
  newUsername: string;
}

interface AuthPasswordUpdatePayload {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}

export async function loginWithCredentials(username: string, password: string) {
  const result = await requestApi<AuthTokenPayload>(apiRoutes.authLogin, {
    auth: false,
    body: {
      username: username.trim(),
      password,
    },
    method: "POST",
  });

  saveAuthSession(result.username, result.accessToken, result.expiresAt);
  return result.username;
}

export function getAuthSetupStatus() {
  return requestApi<AuthSetupStatusPayload>(apiRoutes.authSetup, {
    auth: false,
    cacheTtlMs: 1_000,
    notifyOnError: false,
  });
}

export async function setupAuthOwner(payload: AuthSetupPayload) {
  const result = await requestApi<AuthTokenPayload>(apiRoutes.authSetup, {
    auth: false,
    body: payload,
    method: "POST",
  });

  saveAuthSession(result.username, result.accessToken, result.expiresAt);
  return result.username;
}

export async function refreshAuthSession() {
  const previousToken = getAccessToken();
  if (!previousToken) {
    return false;
  }

  return withAuthSessionLock("exclusive", async () => {
    if (getAccessToken() !== previousToken) {
      return loadAuthSession();
    }

    const result = await requestApi<AuthTokenPayload>(apiRoutes.authRefresh, {
      body: {},
      method: "POST",
    });

    if (getAccessToken() !== previousToken) {
      return loadAuthSession();
    }

    recordInvalidatedToken(previousToken);
    saveAuthSession(result.username, result.accessToken, result.expiresAt);
    return true;
  });
}

export async function updateAuthUsername(payload: AuthUsernameUpdatePayload) {
  return withAuthSessionLock("exclusive", async () => {
    const previousSession = window.localStorage.getItem(AUTH_SESSION_KEY);
    const previousToken = getAccessToken();
    const result = await requestApi<AuthTokenPayload>(apiRoutes.authUsername, {
      body: { ...payload, newUsername: payload.newUsername.trim() },
      method: "POST",
      notifyOnError: false,
    });

    if (window.localStorage.getItem(AUTH_SESSION_KEY) !== previousSession) {
      throw new DOMException("Authentication session changed.", "AbortError");
    }

    saveAuthSession(result.username, result.accessToken, result.expiresAt);
    if (previousToken) recordInvalidatedToken(previousToken);
    return result.username;
  });
}

export async function updateAuthPassword(payload: AuthPasswordUpdatePayload) {
  const previousToken = getAccessToken();
  const result = await requestApi<{ username: string; updated: boolean }>(
    apiRoutes.authPassword,
    {
      body: payload,
      method: "POST",
    },
  );

  if (previousToken) {
    recordInvalidatedToken(previousToken);
  }
  clearAuthSession();

  return result;
}

export { clearAuthSession, loadAuthSession, saveAuthSession };
