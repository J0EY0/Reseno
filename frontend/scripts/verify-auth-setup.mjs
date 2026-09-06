import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const testState = {
  requests: [],
  responses: [],
  savedSessions: [],
  session: null,
  invalidatedTokens: [],
  lockNames: [],
};
globalThis.__RESUMATE_AUTH_SETUP_TEST_STATE__ = testState;
const navigatorDescriptor = Object.getOwnPropertyDescriptor(
  globalThis,
  "navigator",
);
let refreshLock = Promise.resolve();
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    locks: {
      request(name, callback) {
        testState.lockNames.push(name);
        const result = refreshLock.then(callback);
        refreshLock = result.catch(() => {});
        return result;
      },
    },
  },
});

function deferredResponse() {
  let resolve;
  const promise = new Promise((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

const virtualModules = {
  "@/lib/api-client": `
    const state = globalThis.__RESUMATE_AUTH_SETUP_TEST_STATE__;
    export const apiRoutes = {
      authLogin: "/api/auth/login",
      authPassword: "/api/auth/password",
      authRefresh: "/api/auth/refresh",
      authSetup: "/api/auth/setup",
    };
    export async function requestApi(route, options = {}) {
      state.requests.push({ route, options });
      return state.responses.shift();
    }
  `,
  "@/lib/auth-session": `
    const state = globalThis.__RESUMATE_AUTH_SETUP_TEST_STATE__;
    export const AUTH_REFRESH_LOCK_NAME = "resumate-auth-refresh";
    export function clearAuthSession() { state.session = null; }
    export function getAccessToken() { return state.session?.accessToken ?? null; }
    export function loadAuthSession() { return state.session !== null; }
    export function recordInvalidatedToken(token) {
      state.invalidatedTokens.push(token);
    }
    export function saveAuthSession(username, accessToken, expiresAt) {
      state.session = { username, accessToken, expiresAt };
      state.savedSessions.push(state.session);
    }
  `,
};
const virtualImportPrefix = "virtual:resumate-auth-setup-test:";
const virtualPrefix = `\0${virtualImportPrefix}`;
const server = await createServer({
  cacheDir: createViteTestCacheDir(),
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  root: process.cwd(),
  plugins: [
    {
      name: "resumate-auth-setup-test-mocks",
      enforce: "pre",
      resolveId(id) {
        return id.startsWith(virtualImportPrefix) ? `\0${id}` : null;
      },
      load(id) {
        return id.startsWith(virtualPrefix)
          ? virtualModules[id.slice(virtualPrefix.length)]
          : null;
      },
    },
  ],
  resolve: {
    alias: [
      {
        find: "@/lib/api-client",
        replacement: `${virtualImportPrefix}@/lib/api-client`,
      },
      {
        find: "@/lib/auth-session",
        replacement: `${virtualImportPrefix}@/lib/auth-session`,
      },
      { find: "@", replacement: new URL("../src", import.meta.url).pathname },
    ],
  },
  server: { hmr: false, middlewareMode: true, ws: false },
});

try {
  const auth = await server.ssrLoadModule("/src/lib/auth.ts");
  const validation = await server.ssrLoadModule(
    "/src/lib/auth-validation.ts",
  );

  testState.responses.push({ setupRequired: true });
  assert.deepEqual(await auth.getAuthSetupStatus(), { setupRequired: true });
  assert.deepEqual(testState.requests.shift(), {
    route: "/api/auth/setup",
    options: {
      auth: false,
      cacheTtlMs: 1_000,
      notifyOnError: false,
    },
  });

  testState.responses.push({
    username: "owner",
    accessToken: "token-1",
    expiresAt: "2099-01-01T00:00:00Z",
    tokenType: "bearer",
  });
  assert.equal(
    await auth.setupAuthOwner({
      username: "owner",
      password: "password1",
      confirmPassword: "password1",
    }),
    "owner",
  );
  assert.deepEqual(testState.requests.shift(), {
    route: "/api/auth/setup",
    options: {
      auth: false,
      body: {
        username: "owner",
        password: "password1",
        confirmPassword: "password1",
      },
      method: "POST",
    },
  });
  assert.deepEqual(testState.savedSessions, [
    {
      username: "owner",
      accessToken: "token-1",
      expiresAt: "2099-01-01T00:00:00Z",
    },
  ]);

  const refreshedSession = {
    username: "owner",
    accessToken: "token-2",
    expiresAt: "2099-02-01T00:00:00Z",
  };
  testState.responses.push(refreshedSession);
  assert.equal(await auth.refreshAuthSession(), true);
  assert.deepEqual(testState.requests.shift(), {
    route: "/api/auth/refresh",
    options: { body: {}, method: "POST" },
  });
  assert.deepEqual(testState.session, refreshedSession);
  assert.deepEqual(testState.invalidatedTokens, ["token-1"]);

  const concurrentResponse = deferredResponse();
  testState.responses.push(concurrentResponse.promise);
  const concurrentRefreshes = Promise.allSettled([
    auth.refreshAuthSession(),
    auth.refreshAuthSession(),
  ]);
  await setImmediate();
  const concurrentRequestCount = testState.requests.length;
  const nextSession = { ...refreshedSession, accessToken: "token-3" };
  concurrentResponse.resolve(nextSession);
  const concurrentResults = await concurrentRefreshes;
  assert.equal(
    concurrentRequestCount,
    1,
    "Concurrent refreshes must share the rotated token instead of sending it twice.",
  );
  assert.deepEqual(concurrentResults, [
    { status: "fulfilled", value: true },
    { status: "fulfilled", value: true },
  ]);
  assert.deepEqual(testState.session, nextSession);
  assert.deepEqual(testState.invalidatedTokens, ["token-1", "token-2"]);
  assert.equal(testState.savedSessions.length, 3);
  assert.deepEqual(testState.lockNames, Array(3).fill("resumate-auth-refresh"));
  assert.equal(testState.requests.shift().route, "/api/auth/refresh");

  const logoutResponse = deferredResponse();
  testState.responses.push(logoutResponse.promise);
  const refreshBeforeLogout = auth.refreshAuthSession();
  await setImmediate();
  assert.equal(testState.requests.shift().route, "/api/auth/refresh");
  auth.clearAuthSession();
  logoutResponse.resolve({ ...nextSession, accessToken: "logged-out-token" });
  assert.equal(await refreshBeforeLogout, false);
  assert.equal(testState.session, null, "A pending refresh must not undo logout.");
  assert.equal(testState.savedSessions.length, 3);
  assert.deepEqual(testState.invalidatedTokens, ["token-1", "token-2"]);

  const lockCount = testState.lockNames.length;
  assert.equal(await auth.refreshAuthSession(), false);
  assert.equal(
    testState.requests.length,
    0,
    "A refresh without a token must not send a request.",
  );
  assert.equal(testState.lockNames.length, lockCount);

  auth.saveAuthSession("owner", "previous-login", refreshedSession.expiresAt);
  const newLoginResponse = deferredResponse();
  testState.responses.push(newLoginResponse.promise);
  const refreshBeforeNewLogin = auth.refreshAuthSession();
  await setImmediate();
  assert.equal(testState.requests.shift().route, "/api/auth/refresh");
  const newLoginSession = { ...refreshedSession, accessToken: "new-login" };
  auth.saveAuthSession(
    newLoginSession.username,
    newLoginSession.accessToken,
    newLoginSession.expiresAt,
  );
  newLoginResponse.resolve({ ...nextSession, accessToken: "stale-refresh" });
  assert.equal(await refreshBeforeNewLogin, true);
  assert.deepEqual(
    testState.session,
    newLoginSession,
    "A pending refresh must not replace a newer login.",
  );
  assert.equal(testState.savedSessions.length, 5);
  assert.deepEqual(testState.invalidatedTokens, ["token-1", "token-2"]);

  const oauth = await server.ssrLoadModule("/src/lib/auth-oauth.ts");
  const oauthResponse = deferredResponse();
  testState.responses.push(oauthResponse.promise);
  const firstCallback = new AbortController();
  const secondCallback = new AbortController();
  const completing = Promise.allSettled([
    oauth.completeOAuth("entry-retry-code", firstCallback.signal),
    oauth.completeOAuth("entry-retry-code", secondCallback.signal),
  ]);
  firstCallback.abort();
  const oauthSession = { ...refreshedSession, accessToken: "oauth-login" };
  oauthResponse.resolve({ provider: "github", intent: "login", auth: oauthSession });
  const [cancelledCallback, activeCallback] = await completing;
  assert.equal(cancelledCallback.status, "rejected", "An unmounted callback must not accept the shared exchange.");
  assert.equal(cancelledCallback.reason.name, "AbortError");
  assert.deepEqual(activeCallback, { status: "fulfilled", value: { provider: "github", intent: "login" } });
  assert.deepEqual(testState.session, oauthSession);
  assert.equal(testState.savedSessions.length, 6, "Only the active callback may save the exchanged session.");
  assert.deepEqual(await oauth.completeOAuth("entry-retry-code", new AbortController().signal), { provider: "github", intent: "login" },
    "Retrying page preparation must reuse the already completed code exchange.");
  assert.equal(
    testState.savedSessions.length,
    6,
    "Retrying page preparation must not accept the session twice.",
  );
  assert.equal(testState.requests.length, 1, "One callback code must make exactly one exchange request.");
  assert.deepEqual(testState.requests.shift(), {
    route: "/api/auth/oauth/complete",
    options: {
      auth: false,
      body: { code: "entry-retry-code" },
      credentials: "include",
      method: "POST",
      notifyOnError: false,
    },
  });

  auth.clearAuthSession();
  const savesBeforeCancellation = testState.savedSessions.length;
  const cancelledResponse = deferredResponse();
  testState.responses.push(cancelledResponse.promise);
  const cancelledCallers = [new AbortController(), new AbortController()];
  const cancelledCompletions = Promise.allSettled(cancelledCallers.map(({ signal }) =>
    oauth.completeOAuth("abandoned-callback-code", signal),
  ));
  cancelledCallers.forEach((controller) => controller.abort());
  cancelledResponse.resolve({
    provider: "github", intent: "login",
    auth: { ...oauthSession, accessToken: "abandoned-callback-login" },
  });
  for (const result of await cancelledCompletions) {
    assert.equal(result.status, "rejected");
    assert.equal(result.reason.name, "AbortError");
  }
  assert.equal(testState.session, null, "A late exchange must not log in after every caller has cancelled.");
  assert.equal(testState.savedSessions.length, savesBeforeCancellation);
  assert.equal(testState.requests.length, 1, "Cancelled callers must still share one code exchange.");
  assert.equal(testState.requests.shift().options.body.code, "abandoned-callback-code");

  const nextOAuthSession = { ...oauthSession, accessToken: "next-callback-login" };
  testState.responses.push({ provider: "github", intent: "login", auth: nextOAuthSession });
  assert.deepEqual(await oauth.completeOAuth("next-callback-code", new AbortController().signal), {
    provider: "github", intent: "login",
  });
  assert.deepEqual(testState.session, nextOAuthSession, "An abandoned callback must not prevent a new login.");
  assert.equal(testState.savedSessions.length, savesBeforeCancellation + 1);
  assert.equal(testState.requests.length, 1);
  assert.equal(testState.requests.shift().options.body.code, "next-callback-code");

  const savesBeforeAbortedStart = testState.savedSessions.length;
  const abortedStart = new AbortController();
  abortedStart.abort();
  await assert.rejects(
    oauth.completeOAuth("aborted-before-start", abortedStart.signal),
    { name: "AbortError" },
  );
  assert.equal(testState.requests.length, 0);
  assert.equal(testState.savedSessions.length, savesBeforeAbortedStart);

  auth.clearAuthSession();
  await oauth.completeOAuth("next-callback-code", new AbortController().signal);
  assert.equal(testState.session, null, "Reusing an accepted callback must not undo logout.");
  auth.saveAuthSession("owner", "later-login", refreshedSession.expiresAt);
  const savesBeforeReplay = testState.savedSessions.length;
  await oauth.completeOAuth("next-callback-code", new AbortController().signal);
  assert.equal(testState.session.accessToken, "later-login");
  assert.equal(testState.savedSessions.length, savesBeforeReplay);
  assert.equal(testState.requests.length, 0);

  const messages = {
    loginUsernameRequired: "username-required",
    loginUsernameTooShort: "username-short",
    loginUsernameInvalid: "username-invalid",
    loginPasswordRequired: "password-required",
    loginPasswordTooShort: "password-short",
    loginPasswordInvalid: "password-invalid",
    setupConfirmPasswordRequired: "confirmation-required",
    apiMessages: {
      PASSWORD_CONFIRMATION_MISMATCH: "confirmation-mismatch",
    },
  };

  assert.deepEqual(
    validation.validateSetupForm("owner", "password1", "password1", messages),
    {},
  );
  assert.deepEqual(
    validation.validateSetupForm("ab", "password1", "password1", messages),
    { username: "username-short" },
  );
  assert.deepEqual(
    validation.validateSetupForm("owner!", "password1", "password1", messages),
    { username: "username-invalid" },
  );
  assert.deepEqual(
    validation.validateSetupForm("owner", "password", "password", messages),
    { password: "password-invalid" },
  );
  assert.deepEqual(
    validation.validateSetupForm("owner", "password1", "password2", messages),
    { confirmPassword: "confirmation-mismatch" },
  );
  assert.deepEqual(
    validation.validateLoginForm("x", "x", messages),
    {},
    "Login must only require non-empty credentials; setup owns format rules.",
  );

  const appSource = await readFile(
    new URL("../src/App.tsx", import.meta.url),
    "utf8",
  );
  const setupPageSource = await readFile(
    new URL("../src/components/auth/setup-page.tsx", import.meta.url),
    "utf8",
  );
  const authPageShellSource = await readFile(
    new URL("../src/components/auth/auth-page-shell.tsx", import.meta.url),
    "utf8",
  );
  const authSessionSource = await readFile(
    new URL("../src/lib/auth-session.ts", import.meta.url),
    "utf8",
  );
  assert.match(appSource, /authGate\.phase === "setup"/);
  assert.match(appSource, /<Route path="\/setup"/);
  assert.doesNotMatch(
    authPageShellSource,
    /brandTitle|FileText/,
    "The auth shell must not render the redundant brand badge.",
  );
  assert.doesNotMatch(
    setupPageSource,
    /setupFormSubtitle/,
    "The setup form must not render the removed explanatory subtitle.",
  );
  assert.match(
    setupPageSource,
    /confirmPassword === value\s*\? undefined\s*: current\.confirmPassword/,
    "Matching the confirmation through a password edit must clear a stale mismatch error.",
  );
  assert.doesNotMatch(authSessionSource, /import\.meta\.env\.PROD/);

  assert.equal(testState.requests.length, 0);
  assert.equal(testState.responses.length, 0);
  console.log("Authentication setup and refresh coordination verified.");
} finally {
  delete globalThis.__RESUMATE_AUTH_SETUP_TEST_STATE__;
  if (navigatorDescriptor) {
    Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  } else {
    delete globalThis.navigator;
  }
  await server.close();
}
