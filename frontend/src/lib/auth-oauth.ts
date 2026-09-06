import { requestApi } from "@/lib/api-client";
import type { AuthTokenPayload } from "@/lib/auth";
import { saveAuthSession } from "@/lib/auth-session";

export type OAuthProvider = "github";
export type OAuthIntent = "login" | "bind";

export interface OAuthIdentity {
  provider: OAuthProvider;
  label: string;
  createdAt: string;
}

interface OAuthCompletion {
  provider: OAuthProvider;
  intent: OAuthIntent;
  auth: AuthTokenPayload | null;
}

type OAuthResult = Pick<OAuthCompletion, "provider" | "intent">;
const oauthBaseRoute = "/api/auth/oauth";
let completionRequest: {
  code: string;
  promise: Promise<OAuthCompletion>;
  accepted: boolean;
} | null = null;

export function getOAuthIdentities() {
  return requestApi<{
    identities: OAuthIdentity[];
    providers: { provider: OAuthProvider; configured: boolean }[];
  }>(`${oauthBaseRoute}/identities`, {
    cacheTtlMs: 1_000,
    notifyOnError: false,
  });
}

export async function startGitHubSetup() {
  const { registrationUrl, manifest } = await requestApi<{
    registrationUrl: string;
    manifest: Record<string, unknown>;
  }>(`${oauthBaseRoute}/github/setup`, {
    auth: true,
    body: { publicBaseUrl: window.location.origin },
    credentials: "include",
    method: "POST",
    notifyOnError: false,
  });

  const form = document.createElement("form");
  form.action = registrationUrl;
  form.method = "POST";
  form.target = "_self";
  form.hidden = true;
  const input = document.createElement("input");
  input.type = "hidden";
  input.name = "manifest";
  input.value = JSON.stringify(manifest);
  form.appendChild(input);
  document.body.appendChild(form);
  form.submit();
}

export async function requestOAuthAuthorization(
  provider: OAuthProvider,
  intent: OAuthIntent,
) {
  const { authorizationUrl } = await requestApi<{ authorizationUrl: string }>(
    `${oauthBaseRoute}/${provider}/${intent}`,
    {
      auth: intent === "bind",
      body: {},
      credentials: "include",
      method: "POST",
      notifyOnError: false,
    },
  );

  return authorizationUrl;
}

export async function unbindOAuth(provider: OAuthProvider) {
  await requestApi<{ deleted: boolean }>(`${oauthBaseRoute}/${provider}/binding`, {
    method: "DELETE",
    notifyOnError: false,
  });
}

export async function completeOAuth(
  code: string,
  signal: AbortSignal,
): Promise<OAuthResult> {
  signal.throwIfAborted();
  if (completionRequest?.code !== code) {
    completionRequest = {
      code,
      promise: requestApi<OAuthCompletion>(`${oauthBaseRoute}/complete`, {
        auth: false,
        body: { code },
        credentials: "include",
        method: "POST",
        notifyOnError: false,
      }),
      accepted: false,
    };
  }

  const request = completionRequest;
  const { provider, intent, auth } = await request.promise;
  signal.throwIfAborted();
  if (!request.accepted) {
    if (auth) {
      saveAuthSession(auth.username, auth.accessToken, auth.expiresAt);
    }
    request.accepted = true;
  }

  return { provider, intent };
}
