import { requestApi } from "@/lib/api-client";
import type { AuthTokenPayload } from "@/lib/auth";
import { saveAuthSession } from "@/lib/auth-session";

type OAuthProvider = "github";
export type OAuthIntent = "login" | "bind";

export interface OAuthIdentity {
  provider: OAuthProvider;
  label: string;
  createdAt: string;
}

export interface OAuthIdentities {
  identities: OAuthIdentity[];
  providers: { provider: OAuthProvider; configured: boolean }[];
}

export type OAuthIdentitySettingsState =
  { status: "ready"; data: OAuthIdentities } | { status: "error" };

interface OAuthCompletion {
  provider: OAuthProvider;
  intent: OAuthIntent;
  auth: AuthTokenPayload | null;
}

export type OAuthResult = Pick<OAuthCompletion, "provider" | "intent">;
const oauthBaseRoute = "/api/auth/oauth";

export function getOAuthIdentities(signal?: AbortSignal) {
  return requestApi<OAuthIdentities>(`${oauthBaseRoute}/identities`, {
    cacheTtlMs: 1_000,
    notifyOnError: false,
    signal,
  });
}

interface GitHubSetup {
  registrationUrl: string;
  manifest: Record<string, unknown>;
}

export function requestGitHubSetup(signal: AbortSignal) {
  return requestApi<GitHubSetup>(`${oauthBaseRoute}/github/setup`, {
    auth: true,
    body: { publicBaseUrl: window.location.origin },
    credentials: "include",
    method: "POST",
    notifyOnError: false,
    signal,
  });
}

export function submitGitHubSetup(
  target: string,
  { registrationUrl, manifest }: GitHubSetup,
) {
  const form = document.createElement("form");
  form.action = registrationUrl;
  form.method = "POST";
  form.target = target;
  form.hidden = true;
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = "manifest";
  input.value = JSON.stringify(manifest);
  form.appendChild(input);
  document.body.appendChild(form);
  try {
    form.submit();
  } finally {
    form.remove();
  }
}

export async function requestOAuthAuthorization(
  provider: OAuthProvider,
  intent: OAuthIntent,
  signal: AbortSignal,
) {
  const { authorizationUrl } = await requestApi<{ authorizationUrl: string }>(
    `${oauthBaseRoute}/${provider}/${intent}`,
    {
      auth: intent === "bind",
      body: {},
      credentials: "include",
      method: "POST",
      notifyOnError: false,
      signal,
    },
  );

  return authorizationUrl;
}

export async function unbindOAuth(provider: OAuthProvider) {
  await requestApi<{ deleted: boolean }>(
    `${oauthBaseRoute}/${provider}/binding`,
    {
      method: "DELETE",
      notifyOnError: false,
    },
  );
}

export async function completeOAuth(
  code: string,
  signal: AbortSignal,
  expectedIntent: OAuthIntent,
): Promise<OAuthResult> {
  signal.throwIfAborted();
  const { provider, intent, auth } = await requestApi<OAuthCompletion>(
    `${oauthBaseRoute}/complete`,
    {
      auth: false,
      body: { code },
      credentials: "include",
      method: "POST",
      notifyOnError: false,
      signal,
    },
  );
  signal.throwIfAborted();
  if (
    provider !== "github" ||
    intent !== expectedIntent ||
    (intent === "login") !== Boolean(auth)
  ) {
    throw new Error("OAUTH_INVALID_STATE");
  }
  if (auth) {
    saveAuthSession(auth.username, auth.accessToken, auth.expiresAt);
  }

  return { provider, intent };
}
