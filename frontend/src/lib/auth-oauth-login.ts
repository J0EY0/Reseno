import type { AppMessages } from "@/i18n";
import { clearAuthSession, getAccessToken } from "@/lib/auth-session";
import { completeOAuth, requestOAuthAuthorization } from "@/lib/auth-oauth";

export type OAuthLoginCallback = { code: string } | { error: string };

export function resolveOAuthLoginError(
  code: string,
  t: AppMessages,
  fallback = t.oauthStartFailed,
) {
  const message = Object.hasOwn(t.apiMessages, code)
    ? t.apiMessages[code as keyof typeof t.apiMessages]
    : undefined;
  return typeof message === "string" ? message : fallback;
}

export function parseOAuthLoginCallback(
  hash: string,
): OAuthLoginCallback | null {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  if (!params.has("oauth_code") && !params.has("oauth_error")) return null;

  const codes = params.getAll("oauth_code");
  const errors = params.getAll("oauth_error");
  if (codes.length + errors.length !== 1)
    return { error: "OAUTH_INVALID_STATE" };

  const value = codes[0] ?? errors[0];
  if (!value || value.length > 128) return { error: "OAUTH_INVALID_STATE" };
  return codes.length ? { code: value } : { error: value };
}

export async function redirectToGitHubLogin(signal: AbortSignal) {
  signal.throwIfAborted();
  const authorizationUrl = await requestOAuthAuthorization(
    "github",
    "login",
    signal,
  );
  signal.throwIfAborted();
  window.location.assign(authorizationUrl);
}

export async function completeGitHubLogin(
  code: string,
  signal: AbortSignal,
  onComplete: (signal: AbortSignal) => Promise<void>,
) {
  await completeOAuth(code, signal, "login");
  const acceptedToken = getAccessToken();
  try {
    signal.throwIfAborted();
    await onComplete(signal);
  } catch (error) {
    if (signal.aborted && getAccessToken() === acceptedToken)
      clearAuthSession();
    throw error;
  }
}
