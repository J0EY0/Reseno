import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import * as ts from "typescript";

const frontendRoot = new URL("../", import.meta.url);

async function readText(path) {
  return readFile(new URL(path, frontendRoot), "utf8");
}

function collectJsonShape(value, path = "$") {
  if (Array.isArray(value)) {
    return [
      `${path}:array`,
      ...value.flatMap((item, index) => collectJsonShape(item, `${path}[${index}]`)),
    ];
  }

  if (value && typeof value === "object") {
    return [
      `${path}:object`,
      ...Object.keys(value)
        .sort()
        .flatMap((key) => collectJsonShape(value[key], `${path}.${key}`)),
    ];
  }

  return [`${path}:${typeof value}`];
}

function loadMessageModel(source) {
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };
  const localeLoads = [];
  const localeResolvers = new Map();

  vm.runInNewContext(compiled, {
    exports: module.exports,
    module,
    require(specifier) {
      if (specifier === "@/i18n") {
        return {
          loadMessages(locale) {
            localeLoads.push(locale);
            return new Promise((resolve) => {
              localeResolvers.set(locale, resolve);
            });
          },
          locales: ["zh", "en"],
        };
      }

      if (specifier === "@/lib/resume") {
        return { createId: () => "generated-id" };
      }

      return {};
    },
  });

  return { exports: module.exports, localeLoads, localeResolvers };
}

const [
  i18nSource,
  localeHookSource,
  appSource,
  messageModelSource,
  conversationSource,
  sessionHydrationSource,
  enSource,
  zhSource,
] = await Promise.all([
  readText("src/i18n/index.ts"),
  readText("src/i18n/use-locale-messages.ts"),
  readText("src/App.tsx"),
  readText("src/components/copilot/copilot-message-model.ts"),
  readText("src/components/copilot/use-agent-conversation.ts"),
  readText("src/components/copilot/use-agent-session-hydration.ts"),
  readText("src/i18n/locales/en.json"),
  readText("src/i18n/locales/zh.json"),
]);

assert.match(
  i18nSource,
  /import enMessages from ['"]\.\/locales\/en\.json['"]/,
  "The default English locale must remain synchronously available at bootstrap.",
);
assert.doesNotMatch(
  i18nSource,
  /import zhMessages from ['"]\.\/locales\/zh\.json['"]/,
  "The non-default Chinese catalog must not be a static bootstrap dependency.",
);
assert.match(
  i18nSource,
  /zh:\s*\(\)\s*=>\s*import\(['"]\.\/locales\/zh\.json['"]\)/,
  "The Chinese catalog must use a statically analyzable literal dynamic import.",
);
assert.match(
  i18nSource,
  /messageLoadPromises[\s\S]*messageLoadPromises\[locale\][\s\S]*return pendingLoad/,
  "Concurrent requests for one locale must reuse the same in-flight promise.",
);
assert.match(
  i18nSource,
  /\.finally\([\s\S]*delete messageLoadPromises\[locale\]/,
  "Settled locale loads must clear their in-flight entry so failures can retry.",
);

assert.deepEqual(
  collectJsonShape(JSON.parse(zhSource)),
  collectJsonShape(JSON.parse(enSource)),
  "English and Chinese message catalogs must keep the same structural contract.",
);

assert.match(
  localeHookSource,
  /requestIdRef\.current \+= 1/,
  "Locale changes must receive a monotonically increasing request id.",
);
assert.match(
  localeHookSource,
  /requestId !== requestIdRef\.current/,
  "A late locale response must be ignored after a newer request starts.",
);
assert.match(
  localeHookSource,
  /snapshot:\s*\{\s*locale: nextLocale,\s*messages: nextMessages,?\s*\}/,
  "Locale and messages must be committed together in one state update.",
);
assert.doesNotMatch(
  appSource,
  /\[locale, setLocale\]|\[messages, setMessages\]/,
  "App must not maintain independently commit-able locale and message state.",
);
assert.match(
  appSource,
  /onLocaleChange=\{changeLocale\}/,
  "All workspace locale changes must use the guarded atomic transition.",
);
assert.match(
  appSource,
  /if \(isMessagesReady\) \{[\s\S]*?const routeRequest =[\s\S]*?void routeRequest\(\)\.catch/,
  "A non-default catalog and its current lazy route must preload in parallel.",
);

assert.doesNotMatch(
  messageModelSource,
  /getMessagesSync/,
  "The Agent message model must not pull every locale into bootstrap synchronously.",
);
assert.match(
  messageModelSource,
  /Promise\.all\(\[\s*sessionRequest,\s*Promise\.all\(locales\.map\(loadMessages\)\),?\s*\]\)/,
  "Agent session hydration must load its session and all locale catalogs in parallel.",
);
assert.ok(
  (
    `${conversationSource}\n${sessionHydrationSource}`.match(
      /hydrateAgentSession\(/g,
    ) ?? []
  ).length >= 2,
  "Initial and refreshed Agent sessions must both use multilingual hydration.",
);

const enMessages = JSON.parse(enSource);
const zhMessages = JSON.parse(zhSource);
const enTransient = enMessages.agentTransientModelStatusTexts[0];
const zhTransient = zhMessages.agentTransientModelStatusTexts[0];
const session = {
  executions: [],
  messages: [
    { id: "assistant-en", role: "assistant", text: enTransient },
    { id: "assistant-zh", role: "assistant", text: zhTransient },
  ],
  revision: "revision-1",
};
const model = loadMessageModel(messageModelSource);
const converted = model.exports.toPanelMessages(session, [enTransient, zhTransient]);

assert.deepEqual(
  Array.from(converted, (message) => message.text),
  ["", ""],
  "Stored transient status text must be removed for both supported languages.",
);

let resolveSession;
const pendingSession = new Promise((resolve) => {
  resolveSession = resolve;
});
const hydration = model.exports.hydrateAgentSession(pendingSession);

assert.deepEqual(
  Array.from(model.localeLoads).sort(),
  ["en", "zh"],
  "Agent hydration must start both locale loads before the session request settles.",
);

model.localeResolvers.get("en")({
  agentTransientModelStatusTexts: [enTransient],
});
model.localeResolvers.get("zh")({
  agentTransientModelStatusTexts: [zhTransient],
});
resolveSession(session);

const hydrated = await hydration;
assert.deepEqual(
  Array.from(hydrated.panelMessages, (message) => message.text),
  ["", ""],
  "Hydration must pass the multilingual transient-status union into conversion.",
);

console.log("i18n conditional-loading checks passed.");
