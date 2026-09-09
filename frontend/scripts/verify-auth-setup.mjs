import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { setImmediate } from "node:timers/promises";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const testState = {
  now: Date.parse("2026-09-09T00:00:00Z"),
  requests: [],
  requestTokens: [],
  responses: [],
  savedSessions: [],
  session: null,
  invalidatedTokens: [],
  lockNames: [],
};
globalThis.__RESENO_AUTH_SETUP_TEST_STATE__ = testState;
const previousWindow = globalThis.window;
globalThis.window = {
  isSecureContext: true,
  localStorage: {
    getItem(key) {
      assert.equal(key, "reseno-auth-session");
      return testState.session ? JSON.stringify(testState.session) : null;
    },
  },
};
const navigatorDescriptor = Object.getOwnPropertyDescriptor(
  globalThis,
  "navigator",
);
let refreshLock = Promise.resolve();
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    locks: {
      request(name, options, callback) {
        assert.equal(options.mode, "exclusive");
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
    const state = globalThis.__RESENO_AUTH_SETUP_TEST_STATE__;
    export const apiRoutes = {
      authLogin: "/api/auth/login",
      authPassword: "/api/auth/password",
      authRefresh: "/api/auth/refresh",
      authSetup: "/api/auth/setup",
      authUsername: "/api/auth/username",
    };
    export async function requestApi(route, options = {}) {
      state.requests.push({ route, options });
      state.requestTokens.push(state.session?.accessToken ?? null);
      return state.responses.shift();
    }
  `,
  "@/lib/auth-session": `
    const state = globalThis.__RESENO_AUTH_SETUP_TEST_STATE__;
    export const AUTH_SESSION_KEY = "reseno-auth-session";
    export const AUTH_REFRESH_LOCK_NAME = "reseno-auth-refresh";
    export function clearAuthSession() { state.session = null; }
    export function getAccessToken() {
      return Date.parse(state.session?.expiresAt ?? "") > state.now
        ? state.session.accessToken
        : null;
    }
    export function loadAuthSession() { return Boolean(getAccessToken()); }
    export function recordInvalidatedToken(token) {
      state.invalidatedTokens.push(token);
    }
    export function saveAuthSession(username, accessToken, expiresAt) {
      state.session = { username, accessToken, expiresAt };
      state.savedSessions.push(state.session);
    }
  `,
};
const virtualImportPrefix = "virtual:reseno-auth-setup-test:";
const virtualPrefix = `\0${virtualImportPrefix}`;
const server = await createServer({
  cacheDir: createViteTestCacheDir(),
  configFile: false,
  optimizeDeps: { noDiscovery: true },
  root: process.cwd(),
  plugins: [
    {
      name: "reseno-auth-setup-test-mocks",
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
  const validation = await server.ssrLoadModule("/src/lib/auth-validation.ts");

  testState.responses.push({
    setupRequired: true,
    githubLoginAvailable: false,
  });
  assert.deepEqual(await auth.getAuthSetupStatus(), {
    setupRequired: true,
    githubLoginAvailable: false,
  });
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
  assert.deepEqual(testState.lockNames, Array(3).fill("reseno-auth-refresh"));
  assert.equal(testState.requests.shift().route, "/api/auth/refresh");

  const logoutResponse = deferredResponse();
  testState.responses.push(logoutResponse.promise);
  const refreshBeforeLogout = auth.refreshAuthSession();
  await setImmediate();
  assert.equal(testState.requests.shift().route, "/api/auth/refresh");
  auth.clearAuthSession();
  logoutResponse.resolve({ ...nextSession, accessToken: "logged-out-token" });
  assert.equal(await refreshBeforeLogout, false);
  assert.equal(
    testState.session,
    null,
    "A pending refresh must not undo logout.",
  );
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
  const savesBeforeOAuth = testState.savedSessions.length;
  testState.responses.push({ provider: "github", intent: "bind", auth: null });
  await assert.rejects(
    oauth.completeOAuth("wrong-intent", new AbortController().signal, "login"),
    /OAUTH_INVALID_STATE/,
  );
  assert.deepEqual(testState.session, newLoginSession);
  assert.equal(testState.savedSessions.length, savesBeforeOAuth);
  assert.equal(testState.requests.shift().options.body.code, "wrong-intent");

  testState.responses.push({ provider: "github", intent: "bind", auth: null });
  assert.deepEqual(
    await oauth.completeOAuth(
      "bind-code",
      new AbortController().signal,
      "bind",
    ),
    { provider: "github", intent: "bind" },
  );
  assert.deepEqual(
    testState.session,
    newLoginSession,
    "Binding must preserve the current parent session.",
  );
  assert.equal(testState.savedSessions.length, savesBeforeOAuth);
  assert.equal(testState.requests.shift().options.body.code, "bind-code");

  const loginController = new AbortController();
  const oauthSession = { ...refreshedSession, accessToken: "oauth-login" };
  testState.responses.push({
    provider: "github",
    intent: "login",
    auth: oauthSession,
  });
  assert.deepEqual(
    await oauth.completeOAuth("parent-login", loginController.signal, "login"),
    { provider: "github", intent: "login" },
  );
  assert.deepEqual(testState.session, oauthSession);
  assert.equal(testState.savedSessions.length, savesBeforeOAuth + 1);
  assert.deepEqual(testState.requests.shift(), {
    route: "/api/auth/oauth/complete",
    options: {
      auth: false,
      body: { code: "parent-login" },
      credentials: "include",
      method: "POST",
      notifyOnError: false,
      signal: loginController.signal,
    },
  });
  assert.equal(testState.requests.length, 0);

  auth.clearAuthSession();
  const savesBeforeCancellation = testState.savedSessions.length;
  const cancelledResponse = deferredResponse();
  testState.responses.push(cancelledResponse.promise);
  const cancelledController = new AbortController();
  const cancelledCompletion = assert.rejects(
    oauth.completeOAuth("abandoned-popup", cancelledController.signal, "login"),
    { name: "AbortError" },
  );
  cancelledController.abort();
  cancelledResponse.resolve({
    provider: "github",
    intent: "login",
    auth: { ...oauthSession, accessToken: "abandoned-popup-login" },
  });
  await cancelledCompletion;
  assert.equal(
    testState.session,
    null,
    "A cancelled parent must not save a late exchange response.",
  );
  assert.equal(testState.savedSessions.length, savesBeforeCancellation);
  assert.equal(testState.requests.length, 1);
  const cancelledRequest = testState.requests.shift();
  assert.equal(cancelledRequest.options.body.code, "abandoned-popup");
  assert.equal(cancelledRequest.options.signal, cancelledController.signal);
  assert.equal(cancelledRequest.options.signal.aborted, true);

  const nextOAuthSession = { ...oauthSession, accessToken: "next-popup-login" };
  testState.responses.push({
    provider: "github",
    intent: "login",
    auth: nextOAuthSession,
  });
  assert.deepEqual(
    await oauth.completeOAuth(
      "next-popup",
      new AbortController().signal,
      "login",
    ),
    { provider: "github", intent: "login" },
  );
  assert.deepEqual(
    testState.session,
    nextOAuthSession,
    "An abandoned popup must not prevent a new login.",
  );
  assert.equal(testState.savedSessions.length, savesBeforeCancellation + 1);
  assert.equal(testState.requests.shift().options.body.code, "next-popup");

  const savesBeforeAbortedStart = testState.savedSessions.length;
  const abortedStart = new AbortController();
  abortedStart.abort();
  await assert.rejects(
    oauth.completeOAuth("aborted-before-start", abortedStart.signal, "login"),
    { name: "AbortError" },
  );
  assert.equal(testState.requests.length, 0);
  assert.equal(testState.savedSessions.length, savesBeforeAbortedStart);

  const usernamePayload = {
    currentPassword: "password1",
    newUsername: " renamed-owner ",
  };
  const renamedSession = {
    username: "renamed-owner",
    accessToken: "renamed-token",
    expiresAt: refreshedSession.expiresAt,
  };
  auth.saveAuthSession("owner", "before-rename", refreshedSession.expiresAt);
  const locksBeforeRename = testState.lockNames.length;
  testState.responses.push(renamedSession);
  assert.equal(await auth.updateAuthUsername(usernamePayload), "renamed-owner");
  assert.deepEqual(testState.requests.shift(), {
    route: "/api/auth/username",
    options: {
      body: { ...usernamePayload, newUsername: "renamed-owner" },
      method: "POST",
      notifyOnError: false,
    },
  });
  assert.equal(testState.requestTokens.at(-1), "before-rename");
  assert.deepEqual(testState.session, renamedSession);
  assert.equal(testState.invalidatedTokens.at(-1), "before-rename");
  assert.deepEqual(testState.lockNames.slice(locksBeforeRename), [
    "reseno-auth-refresh",
  ]);

  const refreshAhead = deferredResponse();
  const sessionAfterRefresh = {
    ...renamedSession,
    accessToken: "refresh-ahead",
  };
  const sessionAfterQueuedRename = {
    ...renamedSession,
    username: "queued-owner",
    accessToken: "queued-rename",
  };
  testState.responses.push(refreshAhead.promise, sessionAfterQueuedRename);
  const refreshBeforeRename = auth.refreshAuthSession();
  const queuedRename = auth.updateAuthUsername({
    ...usernamePayload,
    newUsername: "queued-owner",
  });
  await setImmediate();
  assert.equal(testState.requests.length, 1);
  assert.equal(testState.requests.shift().route, "/api/auth/refresh");
  refreshAhead.resolve(sessionAfterRefresh);
  assert.equal(await refreshBeforeRename, true);
  assert.equal(await queuedRename, "queued-owner");
  assert.equal(testState.requests.shift().route, "/api/auth/username");
  assert.equal(testState.requestTokens.at(-1), "refresh-ahead");
  assert.deepEqual(testState.session, sessionAfterQueuedRename);
  assert.deepEqual(testState.invalidatedTokens.slice(-2), [
    "renamed-token",
    "refresh-ahead",
  ]);

  const renameAhead = deferredResponse();
  testState.responses.push(renameAhead.promise);
  const renameBeforeRefresh = auth.updateAuthUsername(usernamePayload);
  const queuedRefresh = auth.refreshAuthSession();
  await setImmediate();
  assert.equal(testState.requests.shift().route, "/api/auth/username");
  renameAhead.resolve({ ...renamedSession, accessToken: "rename-ahead" });
  assert.equal(await renameBeforeRefresh, "renamed-owner");
  assert.equal(await queuedRefresh, true);
  assert.equal(testState.requests.length, 0);
  assert.equal(testState.session.accessToken, "rename-ahead");
  assert.equal(testState.invalidatedTokens.at(-1), "queued-rename");

  auth.saveAuthSession(
    "owner",
    "expiring-rename",
    new Date(testState.now + 1_000).toISOString(),
  );
  const expiryResponse = deferredResponse();
  testState.responses.push(expiryResponse.promise);
  const renameDuringExpiry = auth.updateAuthUsername(usernamePayload);
  await setImmediate();
  assert.equal(testState.requests.shift().route, "/api/auth/username");
  assert.equal(testState.requestTokens.at(-1), "expiring-rename");
  testState.now += 1_000;
  assert.equal(auth.loadAuthSession(), false);
  const sessionAfterExpiry = { ...renamedSession, accessToken: "after-expiry" };
  expiryResponse.resolve(sessionAfterExpiry);
  assert.equal(await renameDuringExpiry, "renamed-owner");
  assert.deepEqual(testState.session, sessionAfterExpiry);
  assert.equal(auth.loadAuthSession(), true);
  assert.equal(testState.invalidatedTokens.at(-1), "expiring-rename");

  for (const replaceWithLogin of [false, true]) {
    auth.saveAuthSession("owner", "pending-rename", refreshedSession.expiresAt);
    const renameResponse = deferredResponse();
    testState.responses.push(renameResponse.promise);
    const lateRename = assert.rejects(
      auth.updateAuthUsername(usernamePayload),
      {
        name: "AbortError",
      },
    );
    await setImmediate();
    assert.equal(testState.requests.shift().route, "/api/auth/username");
    if (replaceWithLogin) {
      testState.responses.push(newLoginSession);
      assert.equal(
        await auth.loginWithCredentials("owner", "password1"),
        "owner",
      );
      assert.equal(testState.requests.shift().route, "/api/auth/login");
    } else {
      auth.clearAuthSession();
    }
    const savesBeforeLateRename = testState.savedSessions.length;
    const invalidatedBeforeLateRename = [...testState.invalidatedTokens];
    renameResponse.resolve({ ...renamedSession, accessToken: "stale-rename" });
    await lateRename;
    assert.deepEqual(
      testState.session,
      replaceWithLogin ? newLoginSession : null,
    );
    assert.equal(testState.savedSessions.length, savesBeforeLateRename);
    assert.deepEqual(testState.invalidatedTokens, invalidatedBeforeLateRename);
  }

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

  for (const [currentPassword, newUsername, expected] of [
    ["x", " owner_2 ", {}],
    [
      "",
      "",
      {
        currentPassword: "password-required",
        newUsername: "username-required",
      },
    ],
    ["password1", "ab", { newUsername: "username-short" }],
    ["password1", "owner!", { newUsername: "username-invalid" }],
  ]) {
    assert.deepEqual(
      validation.validateUsernameUpdateForm(
        currentPassword,
        newUsername,
        messages,
      ),
      expected,
    );
  }

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
  const authHeaderSource = authPageShellSource.match(
    /<CardHeader\b[^>]*>([\s\S]*?)<\/CardHeader>/,
  )?.[1];
  assert.ok(authHeaderSource, "The auth shell must retain its form header.");
  assert.match(
    authHeaderSource,
    /<h1\b[^>]*>\s*\{formTitle\}\s*<\/h1>/,
    "The authentication form title must remain the page heading.",
  );
  assert.doesNotMatch(
    authHeaderSource,
    /brandTitle|FileText/,
    "The form header must not repeat the decorative brand badge.",
  );
  assert.match(
    authPageShellSource,
    /<div\b[^>]*aria-hidden="true"[^>]*>\s*<AuthParticleBackground\s*\/>[\s\S]*?<p\b[^>]*>\s*\{brandTitle\}\s*<\/p>/,
    "The brand title must remain in the decorative authentication region.",
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
  console.log(
    "Authentication setup, username changes, and refresh coordination verified.",
  );
} finally {
  delete globalThis.__RESENO_AUTH_SETUP_TEST_STATE__;
  if (previousWindow === undefined) {
    delete globalThis.window;
  } else {
    globalThis.window = previousWindow;
  }
  if (navigatorDescriptor) {
    Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  } else {
    delete globalThis.navigator;
  }
  await server.close();
}
