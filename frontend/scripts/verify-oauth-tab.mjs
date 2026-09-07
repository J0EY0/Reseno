import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { evaluateTypeScript } from "./typescript-module.mjs";

const root = new URL("../", import.meta.url);
const [tabSource, oauthSource] = await Promise.all([
  readFile(new URL("src/lib/auth-oauth-tab.ts", root), "utf8"),
  readFile(new URL("src/lib/auth-oauth.ts", root), "utf8"),
]);
const origin = "https://resume.example.test";
const token = { username: "owner", accessToken: "server-only-jwt", expiresAt: "2099-01-01" };
const t = {
  oauthTabClosed: "closed", oauthTabTimeout: "timeout",
  oauthStartFailed: "failed", apiMessages: { OAUTH_INVALID_STATE: "invalid", OAUTH_CANCELLED: "cancelled" },
};
const plain = (value) => JSON.parse(JSON.stringify(value));
const tick = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function fixture({ completion = { provider: "github", intent: "bind", auth: null }, blocked = false, start, complete, setup } = {}) {
  const requests = [];
  const saves = [];
  const opened = [];
  const messages = [];
  const progress = [];
  const focusHistory = [];
  const forms = [];
  const intervals = new Map();
  const timeouts = new Map();
  const listeners = new Set();
  let timerId = 0;
  let closes = 0;
  let submits = 0;
  const tab = {
    closed: false,
    close() { closes += 1; this.closed = true; },
    focus() { focusHistory.push("tab"); },
    postMessage: (message, target) => messages.push({ message, target }),
  };
  const window = {
    location: { origin },
    open(...args) { opened.push(args); return blocked ? null : tab; },
    focus() { focusHistory.push("parent"); },
    addEventListener(event, fn) { assert.equal(event, "message"); listeners.add(fn); },
    removeEventListener(event, fn) { assert.equal(event, "message"); listeners.delete(fn); },
    setInterval(fn) { const id = ++timerId; intervals.set(id, fn); return id; },
    clearInterval(id) { intervals.delete(id); },
    setTimeout(fn, delay) { const id = ++timerId; timeouts.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timeouts.delete(id); },
  };
  const document = {
    body: { appendChild: (form) => forms.push(form) },
    createElement(name) {
      if (name === "input") return {};
      assert.equal(name, "form");
      return { fields: [], appendChild(input) { this.fields.push(input); }, submit() { submits += 1; }, remove() { this.removed = true; } };
    },
  };
  const requestApi = async (path, options) => {
    requests.push({ path, options });
    if (path.endsWith("/complete")) return complete ? complete.promise : completion;
    if (path.endsWith("/setup")) return setup ? setup.promise : { registrationUrl: "https://github.com/settings/apps/new", manifest: { public: false } };
    return start ? start.promise : { authorizationUrl: "https://github.com/login/oauth/authorize?state=test" };
  };
  const globals = { window, document, AbortController, Error, crypto: { randomUUID: () => "unique-window" } };
  const oauth = evaluateTypeScript(oauthSource, {
    globals,
    imports: { "@/lib/api-client": { requestApi }, "@/lib/auth-session": { saveAuthSession: (...args) => saves.push(args) } },
  });
  const module = evaluateTypeScript(tabSource, { globals, imports: { "@/lib/auth-oauth": oauth } });
  return {
    module, requests, saves, opened, messages, progress, forms, tab, focusHistory,
    authorize(options) { return module.authorizeGitHubBinding({ ...options, onProgress: (value) => progress.push(value) }); },
    allowOpen() { blocked = false; },
    get deadline() { return [...timeouts].find(([, timer]) => timer.delay === 10 * 60 * 1000)?.[0]; },
    get closes() { return closes; }, get submits() { return submits; },
    async send(payload, from = origin, source = tab) {
      await Promise.all([...listeners].map((fn) => fn({ data: payload, origin: from, source })));
    },
    pollClosed() { for (const fn of [...intervals.values()]) fn(); },
    showPreparing() {
      for (const [id, timer] of [...timeouts]) {
        if (timer.delay !== 150) continue;
        timeouts.delete(id);
        timer.fn();
      }
    },
    expire() {
      for (const [id, timer] of [...timeouts]) {
        if (timer.delay !== 10 * 60 * 1000) continue;
        timeouts.delete(id);
        timer.fn();
      }
    },
    assertClean() { assert.equal(listeners.size, 0); assert.equal(intervals.size, 0); assert.equal(timeouts.size, 0); },
  };
}

const tests = [];
const test = (name, run) => tests.push({ name, run });
for (const mode of ["bind", "setup"]) {
  test(`${mode} opens only when authorization is ready and focuses its tab once`, async () => {
    const start = deferred();
    const setup = mode === "setup";
    const intent = "bind";
    const f = fixture({
      ...(setup ? { setup: start } : { start }),
      completion: { provider: "github", intent, auth: null },
    });
    const run = f.authorize({ setup, signal: new AbortController().signal, onComplete: async () => {}, t });
    assert.equal(f.opened.length, 0);
    assert.deepEqual(f.focusHistory, []);
    assert.deepEqual(f.progress, []);
    await tick();
    f.pollClosed();
    await f.send({ type: f.module.OAUTH_TAB_RESULT, code: "premature", intent }, origin, null);
    assert.equal(f.requests.length, 1);
    f.showPreparing();
    assert.deepEqual(plain(f.progress), [{ stage: "preparing" }]);
    start.resolve(setup
      ? { registrationUrl: "https://github.com/settings/apps/new", manifest: {} }
      : { authorizationUrl: "https://github.com/login/oauth/authorize" });
    await tick();
    assert.equal(f.opened.length, 1);
    assert.equal(f.opened[0].length, 2);
    assert.equal(f.opened[0][0], setup ? "" : "https://github.com/login/oauth/authorize");
    assert.match(f.opened[0][1], /^resumate-github-/);
    assert.equal(f.submits, setup ? 1 : 0);
    assert.deepEqual(f.focusHistory, ["tab"]);
    assert.equal(f.progress.at(-1).stage, "waiting");
    f.pollClosed();
    assert.deepEqual(f.focusHistory, ["tab"]);
    await f.send({ type: f.module.OAUTH_TAB_RESULT, code: "focused", intent });
    await run;
    assert.deepEqual(f.focusHistory, ["tab", "parent"]);
    assert.equal(f.progress.at(-1), null);
    f.assertClean();
  });
}

test("wrong origin/source/intent and token-only messages cannot bind; duplicate valid result completes once", async () => {
  const f = fixture();
  const controller = new AbortController();
  const completed = [];
  const run = f.authorize({ signal: controller.signal, onComplete: async (result) => completed.push(result), t });
  await tick();
  f.showPreparing();
  assert.deepEqual(plain(f.progress), [{ stage: "waiting" }]);
  const payload = { type: f.module.OAUTH_TAB_RESULT, code: "once", intent: "bind" };
  await f.send(payload, "https://attacker.example.test");
  await f.send(payload, origin, {});
  await f.send({ ...payload, intent: "login" });
  await f.send({ type: f.module.OAUTH_TAB_RESULT, accessToken: "untrusted-jwt", intent: "bind" });
  assert.equal(f.requests.filter((r) => r.path.endsWith("/complete")).length, 0);
  assert.equal(f.saves.length, 0);
  await Promise.all([f.send({ ...payload, accessToken: "untrusted-jwt" }), f.send(payload)]);
  await run;
  assert.equal(f.tab.closed, true);
  assert.equal(f.closes, 1);
  f.pollClosed();
  f.expire();
  controller.abort();
  await f.send({ ...payload, code: "late-message" });
  assert.equal(f.closes, 1);
  assert.equal(f.requests.filter((r) => r.path.endsWith("/complete")).length, 1);
  assert.deepEqual(f.saves, []);
  assert.equal(completed.length, 1);
  assert.deepEqual(plain(f.messages), [{ message: { type: f.module.OAUTH_TAB_RECEIVED }, target: origin }]);
  f.assertClean();
});

for (const completion of [
  { provider: "github", intent: "login", auth: token },
  { provider: "github", intent: "bind", auth: token },
]) {
  test(`authoritative ${completion.intent}/${Boolean(completion.auth)} mismatch never saves a JWT`, async () => {
    const f = fixture({ completion });
    const run = f.authorize({ signal: new AbortController().signal, onComplete: async () => assert.fail("Unexpected completion"), t });
    const rejected = assert.rejects(run, /invalid/);
    await tick();
    await f.send({ type: f.module.OAUTH_TAB_RESULT, code: "invalid", intent: "bind" });
    await rejected;
    assert.equal(f.saves.length, 0);
    f.assertClean();
  });
}

test("an already-aborted flow neither requests authorization nor opens a tab", async () => {
  const f = fixture();
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(f.authorize({ signal: controller.signal, onComplete: async () => {}, t }), { name: "AbortError" });
  assert.equal(f.opened.length, 0);
  assert.equal(f.requests.length, 0);
  assert.deepEqual(f.progress, []);
  f.assertClean();
});

for (const setup of [false, true]) {
  test(`${setup ? "setup" : "binding"} resumes a blocked open without requesting a new authorization or deadline`, async () => {
    const intent = "bind";
    const f = fixture({ blocked: true, completion: { provider: "github", intent, auth: null } });
    const run = f.authorize({ setup, signal: new AbortController().signal, onComplete: async () => {}, t });
    const deadline = f.deadline;
    assert.notEqual(deadline, undefined);
    await tick();
    assert.equal(f.progress.at(-1).stage, "blocked");
    const open = f.progress.at(-1).open;
    assert.equal(f.submits, 0);
    assert.deepEqual(f.focusHistory, []);
    f.pollClosed();
    f.showPreparing();
    await f.send({ type: f.module.OAUTH_TAB_RESULT, code: "unopened", intent }, origin, null);
    assert.equal(f.requests.length, 1);
    assert.equal(f.progress.at(-1).stage, "blocked");
    open();
    assert.equal(f.opened.length, 2);
    assert.equal(f.requests.length, 1);
    assert.equal(f.submits, 0);
    assert.equal(f.deadline, deadline);
    f.allowOpen();
    open();
    assert.equal(f.opened.length, 3);
    assert.deepEqual(f.opened[2], f.opened[0]);
    assert.deepEqual(f.focusHistory, ["tab"]);
    assert.equal(f.submits, setup ? 1 : 0);
    assert.equal(f.progress.at(-1).stage, "waiting");
    assert.equal(f.requests.length, 1);
    assert.equal(f.deadline, deadline);
    open();
    assert.equal(f.opened.length, 3);
    await f.send({ type: f.module.OAUTH_TAB_RESULT, code: "resumed", intent });
    await run;
    open();
    assert.equal(f.opened.length, 3);
    assert.equal(f.progress.at(-1), null);
    f.assertClean();
  });
}

for (const ending of ["abort", "timeout"]) {
  test(`${ending} invalidates a blocked open callback without opening or focusing any window`, async () => {
    const f = fixture({ blocked: true });
    const controller = new AbortController();
    const run = f.authorize({ signal: controller.signal, onComplete: async () => assert.fail("Unexpected completion"), t });
    const rejected = assert.rejects(run, ending === "abort" ? { name: "AbortError" } : /timeout/);
    await tick();
    const open = f.progress.at(-1).open;
    if (ending === "abort") controller.abort();
    else f.expire();
    await rejected;
    f.allowOpen();
    open();
    assert.equal(f.opened.length, 1);
    assert.equal(f.closes, 0);
    assert.deepEqual(f.focusHistory, []);
    assert.equal(f.requests.length, 1);
    assert.equal(f.progress.at(-1), null);
    f.assertClean();
  });
}

for (const ending of ["abort", "close", "timeout", "cancel"]) {
  test(`${ending} cleans listeners/timers and prevents late authorization work`, async () => {
    const start = deferred();
    const f = fixture({ start });
    const controller = new AbortController();
    const run = f.authorize({ signal: controller.signal, onComplete: async () => assert.fail("Unexpected completion"), t });
    const rejected = assert.rejects(run, ending === "abort" ? { name: "AbortError" } : new RegExp(ending === "cancel" ? "cancelled" : ending === "close" ? "closed" : "timeout"));
    const opened = ending === "close" || ending === "cancel";
    if (opened) {
      start.resolve({ authorizationUrl: "https://github.com/login/oauth/authorize" });
      await tick();
    }
    if (ending === "abort") controller.abort();
    if (ending === "close") { f.tab.closed = true; f.pollClosed(); }
    if (ending === "timeout") f.expire();
    if (ending === "cancel") await f.send({ type: f.module.OAUTH_TAB_RESULT, error: "OAUTH_CANCELLED" });
    await rejected;
    start.resolve({ authorizationUrl: "https://github.com/late-response" });
    await tick();
    assert.equal(f.opened.length, opened ? 1 : 0);
    assert.deepEqual(f.focusHistory, opened ? ["tab", "parent"] : []);
    assert.equal(f.saves.length, 0);
    assert.equal(f.requests[0].options.signal.aborted, true);
    assert.equal(f.progress.at(-1), null);
    f.assertClean();
  });
}

for (const ending of ["close", "timeout"]) {
  test(`${ending} during code exchange suppresses late binding completion`, async () => {
    const complete = deferred();
    const f = fixture({ complete });
    const run = f.authorize({ signal: new AbortController().signal, onComplete: async () => assert.fail("Unexpected completion"), t });
    const rejected = assert.rejects(run, ending === "close" ? /closed/ : /timeout/);
    await tick();
    const message = f.send({ type: f.module.OAUTH_TAB_RESULT, code: "late", intent: "bind" });
    await tick();
    if (ending === "close") { f.tab.closed = true; f.pollClosed(); }
    else f.expire();
    assert.equal(f.requests.find((request) => request.path.endsWith("/complete")).options.signal.aborted, true);
    await rejected;
    complete.resolve({ provider: "github", intent: "bind", auth: null });
    await message;
    assert.equal(f.saves.length, 0);
    f.assertClean();
  });

  test(`${ending} cancels the parent completion work before it can update the page`, async () => {
    const prepared = deferred();
    const f = fixture({ completion: { provider: "github", intent: "bind", auth: null } });
    let completionSignal;
    let updates = 0;
    const run = f.authorize({
      signal: new AbortController().signal, t,
      onComplete: async (_result, signal) => {
        completionSignal = signal;
        await prepared.promise;
        signal.throwIfAborted();
        updates += 1;
      },
    });
    const rejected = assert.rejects(run, ending === "close" ? /closed/ : /timeout/);
    await tick();
    const message = f.send({ type: f.module.OAUTH_TAB_RESULT, code: "bound", intent: "bind" });
    await tick();
    assert.equal(completionSignal.aborted, false);
    if (ending === "close") { f.tab.closed = true; f.pollClosed(); }
    else f.expire();
    assert.equal(completionSignal.aborted, true);
    await rejected;
    prepared.resolve();
    await message;
    assert.equal(updates, 0);
    f.assertClean();
  });
}

test("setup submits manifest into the exact named tab and removes its form", async () => {
  const f = fixture({ completion: { provider: "github", intent: "bind", auth: null } });
  const run = f.authorize({ setup: true, signal: new AbortController().signal, onComplete: async () => {}, t });
  await tick();
  assert.equal(f.forms[0].target, f.opened[0][1]);
  assert.notEqual(f.forms[0].target, "_self");
  assert.equal(f.forms[0].fields[0].name, "manifest");
  assert.equal(f.forms[0].removed, true);
  await f.send({ type: f.module.OAUTH_TAB_RESULT, code: "setup", intent: "bind" });
  await run;
  assert.equal(f.saves.length, 0);
  f.assertClean();
});

test("an aborted late setup response never submits a form", async () => {
  const setup = deferred();
  const f = fixture({ setup });
  const controller = new AbortController();
  const run = f.authorize({ setup: true, signal: controller.signal, onComplete: async () => assert.fail("Unexpected completion"), t });
  const rejected = assert.rejects(run, { name: "AbortError" });
  controller.abort();
  setup.resolve({ registrationUrl: "https://github.com/settings/apps/new", manifest: {} });
  await rejected;
  await tick();
  assert.equal(f.submits, 0);
  assert.equal(f.opened.length, 0);
  assert.deepEqual(f.focusHistory, []);
  f.assertClean();
});

let failures = 0;
for (const { name, run } of tests) {
  try { await run(); process.stdout.write(`PASS ${name}\n`); }
  catch (error) { failures += 1; process.stdout.write(`FAIL ${name}: ${error.message}\n`); }
}
process.stdout.write(`${tests.length - failures}/${tests.length} passed\n`);
process.exitCode = failures ? 1 : 0;
