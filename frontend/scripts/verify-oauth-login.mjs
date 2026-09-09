import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { evaluateTypeScript } from "./typescript-module.mjs";

const root = new URL("../", import.meta.url);
const [loginSource, oauthSource] = await Promise.all([
  readFile(new URL("src/lib/auth-oauth-login.ts", root), "utf8"),
  readFile(new URL("src/lib/auth-oauth.ts", root), "utf8"),
]);
const token = {
  username: "owner",
  accessToken: "login-jwt",
  expiresAt: "2099-01-01",
};
const plain = (value) => JSON.parse(JSON.stringify(value));
const tick = async () => {
  for (let i = 0; i < 8; i += 1) await Promise.resolve();
};
function deferred() {
  let resolve;
  const promise = new Promise((accept) => {
    resolve = accept;
  });
  return { promise, resolve };
}

function fixture({
  start,
  complete,
  completion = { provider: "github", intent: "login", auth: token },
} = {}) {
  const requests = [];
  const navigations = [];
  const saves = [];
  let accessToken = null;
  const session = {
    getAccessToken: () => accessToken,
    clearAuthSession: () => {
      accessToken = null;
    },
    saveAuthSession: (...args) => {
      saves.push(args);
      accessToken = args[1];
    },
  };
  const globals = {
    window: {
      location: { assign: (url) => navigations.push(url) },
      open: () => assert.fail("Login must use the current tab"),
      focus: () => assert.fail("Login must not switch window focus"),
    },
    URLSearchParams,
    AbortController,
    Error,
  };
  const oauth = evaluateTypeScript(oauthSource, {
    globals,
    imports: {
      "@/lib/api-client": {
        requestApi: async (path, options) => {
          requests.push({ path, options });
          if (path.endsWith("/complete"))
            return complete ? complete.promise : completion;
          return start
            ? start.promise
            : {
                authorizationUrl:
                  "https://github.com/login/oauth/authorize?state=server",
              };
        },
      },
      "@/lib/auth-session": session,
    },
  });
  const login = evaluateTypeScript(loginSource, {
    globals,
    imports: { "@/lib/auth-oauth": oauth, "@/lib/auth-session": session },
  });
  return { login, requests, navigations, saves, session };
}

const tests = [];
const test = (name, run) => tests.push({ name, run });

test("callback parser accepts only one bounded code or error", () => {
  const { login } = fixture();
  assert.equal(login.parseOAuthLoginCallback("#section"), null);
  assert.deepEqual(plain(login.parseOAuthLoginCallback("#oauth_code=once")), {
    code: "once",
  });
  assert.deepEqual(
    plain(login.parseOAuthLoginCallback("#oauth_error=OAUTH_CANCELLED")),
    { error: "OAUTH_CANCELLED" },
  );
  for (const hash of [
    "#oauth_code=",
    "#oauth_error=",
    "#oauth_code=one&oauth_code=two",
    "#oauth_error=one&oauth_error=two",
    "#oauth_code=one&oauth_error=two",
    `#oauth_code=${"a".repeat(129)}`,
    `#oauth_error=${"a".repeat(129)}`,
  ]) {
    assert.deepEqual(plain(login.parseOAuthLoginCallback(hash)), {
      error: "OAUTH_INVALID_STATE",
    });
  }
});

test("untrusted callback errors cannot read inherited properties or render arbitrary values", () => {
  const { login } = fixture();
  const t = {
    oauthStartFailed: "failed",
    apiMessages: {
      OAUTH_CANCELLED: "cancelled",
      OAUTH_INVALID_STATE: "invalid",
      wrong: {},
    },
  };
  assert.equal(login.resolveOAuthLoginError("OAUTH_CANCELLED", t), "cancelled");
  for (const error of [
    "__proto__",
    "constructor",
    "toString",
    "hasOwnProperty",
    "wrong",
    "untrusted text",
  ]) {
    const callback = login.parseOAuthLoginCallback(
      `#oauth_error=${encodeURIComponent(error)}`,
    );
    assert.equal(login.resolveOAuthLoginError(callback.error, t), "failed");
  }
});

test("login fetches its final URL then navigates the current tab", async () => {
  const start = deferred();
  const f = fixture({ start });
  const signal = new AbortController().signal;
  const run = f.login.redirectToGitHubLogin(signal);
  assert.deepEqual(f.navigations, []);
  assert.equal(f.requests[0].path, "/api/auth/oauth/github/login");
  assert.equal(f.requests[0].options.auth, false);
  assert.equal(f.requests[0].options.signal, signal);
  start.resolve({ authorizationUrl: "https://github.com/final-authorization" });
  await run;
  assert.deepEqual(f.navigations, ["https://github.com/final-authorization"]);
});

test("cancel before URL readiness prevents navigation even if the server finishes late", async () => {
  const start = deferred();
  const f = fixture({ start });
  const controller = new AbortController();
  const run = f.login.redirectToGitHubLogin(controller.signal);
  const rejected = assert.rejects(run, { name: "AbortError" });
  controller.abort();
  start.resolve({ authorizationUrl: "https://github.com/late" });
  await rejected;
  assert.deepEqual(f.navigations, []);
});

test("an already cancelled login does not request authorization", async () => {
  const f = fixture();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(f.login.redirectToGitHubLogin(controller.signal), {
    name: "AbortError",
  });
  assert.deepEqual(f.requests, []);
});

test("callback exchanges once and waits for the destination commit", async () => {
  const f = fixture();
  const committed = deferred();
  const controller = new AbortController();
  let finished = false;
  let calls = 0;
  const run = f.login
    .completeGitHubLogin(
      "single-use-code",
      controller.signal,
      async (signal) => {
        calls += 1;
        assert.equal(signal, controller.signal);
        assert.equal(f.session.getAccessToken(), token.accessToken);
        await committed.promise;
        signal.throwIfAborted();
      },
    )
    .then(() => {
      finished = true;
    });
  await tick();
  assert.equal(calls, 1);
  assert.equal(finished, false);
  assert.equal(f.requests.length, 1);
  assert.deepEqual(plain(f.requests[0].options.body), {
    code: "single-use-code",
  });
  committed.resolve();
  await run;
  assert.equal(finished, true);
  assert.deepEqual(f.navigations, []);
});

test("cancelling exchange prevents a late response from saving a JWT", async () => {
  const complete = deferred();
  const f = fixture({ complete });
  const controller = new AbortController();
  const run = f.login.completeGitHubLogin(
    "cancelled",
    controller.signal,
    async () => assert.fail("Unexpected completion"),
  );
  const rejected = assert.rejects(run, { name: "AbortError" });
  controller.abort();
  complete.resolve({ provider: "github", intent: "login", auth: token });
  await rejected;
  assert.deepEqual(f.saves, []);
});

for (const changedSession of [false, true]) {
  test(`cancel during destination readiness ${changedSession ? "preserves a newer session" : "clears this login session"}`, async () => {
    const f = fixture();
    const committed = deferred();
    const controller = new AbortController();
    const run = f.login.completeGitHubLogin(
      "cancelled",
      controller.signal,
      async (signal) => {
        await committed.promise;
        signal.throwIfAborted();
      },
    );
    const rejected = assert.rejects(run, { name: "AbortError" });
    await tick();
    if (changedSession)
      f.session.saveAuthSession("owner", "new-login-jwt", token.expiresAt);
    controller.abort();
    committed.resolve();
    await rejected;
    assert.equal(
      f.session.getAccessToken(),
      changedSession ? "new-login-jwt" : null,
    );
  });
}

for (const completion of [
  { provider: "github", intent: "bind", auth: null },
  { provider: "github", intent: "login", auth: null },
]) {
  test(`a ${completion.intent} callback with no login session cannot authenticate`, async () => {
    const f = fixture({ completion });
    await assert.rejects(
      f.login.completeGitHubLogin(
        "wrong-intent",
        new AbortController().signal,
        async () => assert.fail("Unexpected completion"),
      ),
      /OAUTH_INVALID_STATE/,
    );
    assert.deepEqual(f.saves, []);
  });
}

let failures = 0;
for (const { name, run } of tests) {
  try {
    await run();
    process.stdout.write(`PASS ${name}\n`);
  } catch (error) {
    failures += 1;
    process.stdout.write(`FAIL ${name}: ${error.message}\n`);
  }
}
process.stdout.write(`${tests.length - failures}/${tests.length} passed\n`);
process.exitCode = failures ? 1 : 0;
