import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const testState = {
  requests: [],
  responses: [],
  savedSessions: [],
};
globalThis.__RESUMATE_AUTH_SETUP_TEST_STATE__ = testState;

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
    export function clearAuthSession() {}
    export function getAccessToken() { return null; }
    export function loadAuthSession() { return false; }
    export function recordInvalidatedToken() {}
    export function saveAuthSession(username, accessToken, expiresAt) {
      state.savedSessions.push({ username, accessToken, expiresAt });
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
  console.log("First-run authentication setup verified.");
} finally {
  delete globalThis.__RESUMATE_AUTH_SETUP_TEST_STATE__;
  await server.close();
}
