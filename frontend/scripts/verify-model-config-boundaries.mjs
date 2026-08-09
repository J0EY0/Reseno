import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const frontendRoot = new URL("../", import.meta.url);

async function readText(path) {
  return readFile(new URL(path, frontendRoot), "utf8");
}

const [popover, controller, draft, providerFields, modelFields] =
  await Promise.all([
    readText("src/components/model-config-form-popover.tsx"),
    readText("src/components/models/use-model-config-dialog.ts"),
    readText("src/components/models/model-config-draft.ts"),
    readText("src/components/models/model-config-provider-fields.tsx"),
    readText("src/components/models/model-config-model-fields.tsx"),
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
assert.doesNotMatch(
  `${providerFields}\n${modelFields}`,
  /name="model-temperature"|name="model-top-p"/,
  "Removed temperature and topP controls must not return.",
);

console.log("Model config boundaries verified.");
