import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

import { createViteTestCacheDir } from "./vite-test-cache.mjs";

const frontendRoot = new URL("../", import.meta.url);

async function readText(path) {
  return readFile(new URL(path, frontendRoot), "utf8");
}

const [
  popover,
  modelDialog,
  controller,
  draft,
  providerFields,
  modelFields,
  modelConfigLibrary,
  resumeTypes,
] =
  await Promise.all([
    readText("src/components/model-config-form-popover.tsx"),
    readText("src/components/models/model-config-dialog.tsx"),
    readText("src/components/models/use-model-config-dialog.ts"),
    readText("src/components/models/model-config-draft.ts"),
    readText("src/components/models/model-config-provider-fields.tsx"),
    readText("src/components/models/model-config-model-fields.tsx"),
    readText("src/lib/model-config.ts"),
    readText("src/types/resume.ts"),
  ]);

assert.match(
  popover,
  /import\("@\/components\/models\/model-config-dialog"\)/,
  "The model dialog must remain a statically analyzable dynamic import.",
);
assert.match(
  popover,
  /\{open \? \([\s\S]*?<LazyModelConfigDialog/,
  "Provider metadata and the heavy form must stay deferred until the dialog opens.",
);
assert.match(
  popover,
  /onFocus=\{\(\) => void loadModelConfigDialog\(\)\}[\s\S]*onPointerEnter=\{\(\) => void loadModelConfigDialog\(\)\}/,
  "The dialog chunk should preload from clear user intent.",
);
assert.match(
  popover,
  /<DialogTitle className="sr-only">[\s\S]*?<DialogDescription className="sr-only">/,
  "The lazy dialog fallback must retain an accessible title and description.",
);

assert.match(
  controller,
  /void getModelProviders\(\)/,
  "The dialog controller must own provider metadata loading.",
);
assert.match(
  controller,
  /discoverModels\(\{[\s\S]*apiUrl:\s*modelDiscoveryApiUrl/,
  "Model discovery must use the resolved provider API URL.",
);
assert.match(
  controller,
  /refresh:\s*true/,
  "Only explicit refreshes may bypass the cached model list.",
);
assert.match(
  controller,
  /models\.length === 1 \? models\[0\] : null/,
  "Discovery must only auto-select a model when exactly one result exists.",
);
assert.match(
  controller,
  /status:\s*"invalid",\s*errors:\s*nextErrors/,
  "Validation failures must expose the invalid fields to the submit handler.",
);
assert.match(
  modelDialog,
  /result\.status === "invalid"[\s\S]*?focusFirstModelConfigError\(/,
  "Invalid submission must focus the first invalid control inside the dialog form.",
);
assert.match(
  modelDialog,
  /<form[\s\S]*?ref=\{formRef\}/,
  "Invalid-field focus must stay scoped to the active model form.",
);

assert.match(
  draft,
  /provider\.id === "custom-cloud"[\s\S]*messages\.customCloudApi/,
  "The Custom Cloud API label must stay localized.",
);
assert.match(
  draft,
  /provider\.kind === "local"[\s\S]*messages\.localProvider[\s\S]*messages\.cloudProvider/,
  "Provider kind labels must distinguish local and cloud providers.",
);
assert.match(
  draft,
  /draft\.providerKind === "cloud"[\s\S]*provider\.defaultBaseUrl\.trim\(\)[\s\S]*draft\.apiUrl\.trim\(\)/,
  "Saved cloud configs must use the manifest URL while local configs keep the typed URL.",
);
assert.match(
  draft,
  /temperature:\s*null,[\s\S]*topP:\s*null/,
  "The form must not persist the removed sampling controls.",
);

assert.match(
  providerFields,
  /providersLoaded && draft\.providerKind !== "cloud"[\s\S]*name="model-api-url"/,
  "Only local/manual providers may expose a typed API URL.",
);
assert.match(
  providerFields,
  /providerDisplayLabel\([\s\S]*ProviderKindBadge/,
  "Provider options must share the localized label and kind badge.",
);
assert.match(
  providerFields,
  /<SelectTrigger[\s\S]*?id="model-provider"[\s\S]*?aria-invalid=\{Boolean\(errors\.provider\)\}/,
  "The provider trigger must expose its invalid state.",
);

assert.match(
  modelFields,
  /onValueChange=\{selectModel\}[\s\S]*className="w-full"[\s\S]*position="popper"/,
  "Cloud models must use the full-width discovered-model popper.",
);
assert.match(
  modelFields,
  /id="model-supports-tools"[\s\S]*updateField\("supportsTools", checked === true\)/,
  "Manual configs must preserve tool capability editing.",
);
assert.match(
  modelFields,
  /messages\.capabilities[\s\S]*messages\.advancedSettings[\s\S]*name="model-context-window"[\s\S]*name="model-max-tokens"/,
  "Manual configs must preserve capabilities and token limits.",
);
assert.match(
  modelFields,
  /<SelectTrigger[\s\S]*?id="model-select"[\s\S]*?aria-invalid=\{Boolean\(errors\.model \|\| errors\.discovery\)\}/,
  "The discovered-model trigger must expose its invalid state.",
);
assert.match(
  modelFields,
  /id="model-discovery"/,
  "The discovery action must remain an explicit focus fallback.",
);
assert.doesNotMatch(
  `${providerFields}\n${modelFields}`,
  /name="model-temperature"|name="model-top-p"/,
  "Removed temperature and topP controls must not return.",
);
assert.doesNotMatch(
  `${modelConfigLibrary}\n${resumeTypes}`,
  /\bLegacyModelConfig\b/,
  "The frontend must not retain a legacy model config type or normalization path.",
);

const server = await createServer({
  cacheDir: createViteTestCacheDir(),
  appType: "custom",
  configFile: false,
  logLevel: "silent",
  optimizeDeps: { noDiscovery: true },
  root: frontendRoot.pathname,
  server: { hmr: false, middlewareMode: true, ws: false },
  resolve: {
    alias: { "@": new URL("src/", frontendRoot).pathname },
  },
});

try {
  const { focusFirstModelConfigError } = await server.ssrLoadModule(
    "/src/components/models/model-config-focus.ts",
  );
  const focusedIds = [];
  const focusTargets = new Map(
    ["model-api-key", "model-select", "model-discovery"].map((id) => [
      `#${id}`,
      {
        disabled: id === "model-select",
        focus() {
          focusedIds.push(id);
        },
      },
    ]),
  );
  const focusRoot = {
    querySelector(selector) {
      return focusTargets.get(selector) ?? null;
    },
  };
  assert.equal(
    focusFirstModelConfigError(
      focusRoot,
      { apiKey: "Required", model: "Required" },
      "cloud",
    ),
    true,
  );
  assert.deepEqual(
    focusedIds,
    ["model-api-key"],
    "Cloud validation must focus the API key before the later model control.",
  );
  focusedIds.length = 0;
  assert.equal(
    focusFirstModelConfigError(
      focusRoot,
      { model: "Required", discovery: "Fetch models" },
      "cloud",
    ),
    true,
  );
  assert.deepEqual(
    focusedIds,
    ["model-discovery"],
    "A disabled model select must fall back to the model discovery action.",
  );

  const { normalizeModelConfigs } = await server.ssrLoadModule(
    "/src/lib/model-config.ts",
  );
  assert.deepEqual(
    normalizeModelConfigs(
      {
        modelConfig: {
          provider: "openai",
          model: "legacy-model",
        },
      },
      "en",
    ),
    [],
    "The removed singular modelConfig field must not hydrate workspace models.",
  );
  const canonicalModelConfig = {
    id: "model-canonical",
    provider: "openai",
    providerLabel: "OpenAI",
    iconProvider: "openai",
    providerKind: "cloud",
    apiFamily: "openai_responses",
    nickname: "Primary model",
    apiKeyPreview: "sk-••••",
    model: "gpt-test",
    apiUrl: "https://api.openai.com/v1",
    temperature: null,
    topP: null,
    maxTokens: 4096,
    contextWindowTokens: 128000,
    supportsImage: true,
    supportsThinking: true,
    supportsTools: true,
    supportsStreaming: true,
    thinkingEnabled: true,
  };
  assert.deepEqual(
    normalizeModelConfigs({ modelConfigs: [canonicalModelConfig] }, "en"),
    [canonicalModelConfig],
    "The canonical modelConfigs array must remain the workspace model contract.",
  );

  const { ModelConfigFormPopover } = await server.ssrLoadModule(
    "/src/components/model-config-form-popover.tsx",
  );
  const createTriggerMarkup = renderToStaticMarkup(
    React.createElement(ModelConfigFormPopover, {
      locale: "en",
      mode: "create",
      onSubmit() {},
      t: { addModelConfig: "Add model" },
    }),
  );
  const editTriggerMarkup = renderToStaticMarkup(
    React.createElement(ModelConfigFormPopover, {
      locale: "en",
      mode: "edit",
      onSubmit() {},
      t: { addModelConfig: "Add model" },
      trigger: React.createElement("button", { type: "button" }, "Edit model"),
    }),
  );

  for (const [label, triggerMarkup] of [
    ["add-model", createTriggerMarkup],
    ["edit-model", editTriggerMarkup],
  ]) {
    assert.match(
      triggerMarkup,
      /aria-haspopup="dialog"/,
      `The rendered ${label} button must receive the Radix dialog trigger behavior.`,
    );
    assert.match(
      triggerMarkup,
      /aria-expanded="false"/,
      `The rendered ${label} button must expose its closed dialog state.`,
    );
  }
} finally {
  await server.close();
}

console.log("Model config boundaries verified.");
