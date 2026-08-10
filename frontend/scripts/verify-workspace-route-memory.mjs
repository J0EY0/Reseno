import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import * as ts from "typescript";

const moduleUrl = new URL(
  "../src/lib/workspace-route-memory.ts",
  import.meta.url,
);
const source = await readFile(moduleUrl, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
  fileName: "workspace-route-memory.ts",
}).outputText;
const module = { exports: {} };

vm.runInNewContext(compiled, {
  exports: module.exports,
  module,
}, { filename: "workspace-route-memory.js" });

const {
  clearWorkspaceLateralRouteMemory,
  createWorkspaceLateralRouteHandoff,
  deleteWorkspaceLateralRouteHandoff,
  rememberWorkspaceLateralRoute,
  resolveWorkspaceLateralRoute,
} = module.exports;

const resume = {
  data: {
    customTemplates: [],
    defaultTemplateId: "minimal",
    resumes: [],
    theme: "light",
  },
  view: "resume",
};
const settings = {
  data: {
    agentSettings: {},
    modelConfigs: [],
    theme: "dark",
  },
  view: "settings",
};

rememberWorkspaceLateralRoute(resume);
const settingsState = createWorkspaceLateralRouteHandoff(settings);
assert.equal(
  Object.prototype.hasOwnProperty.call(settingsState, "data"),
  false,
  "Browser history must contain only a small token, never the route DTO.",
);

const arrival = resolveWorkspaceLateralRoute(settingsState, "settings");
assert.equal(arrival.data, settings.data);
assert.equal(arrival.shouldScrubHistory, true);
assert.equal(arrival.tokenToDelete, settingsState.token);
deleteWorkspaceLateralRouteHandoff(arrival.tokenToDelete);

const back = resolveWorkspaceLateralRoute(null, "resume");
assert.equal(
  back.data,
  resume.data,
  "Same-session POP must seed its first frame from the latest view snapshot.",
);

const deadToken = resolveWorkspaceLateralRoute(settingsState, "settings");
assert.equal(deadToken.data, settings.data);
assert.equal(
  deadToken.shouldScrubHistory,
  true,
  "A consumed token must be removed from browser history.",
);

clearWorkspaceLateralRouteMemory();
assert.equal(resolveWorkspaceLateralRoute(null, "resume").data, null);
const clearedDeadToken = resolveWorkspaceLateralRoute(
  settingsState,
  "settings",
);
assert.equal(clearedDeadToken.data, null);
assert.equal(clearedDeadToken.shouldScrubHistory, true);

console.log("Workspace route memory verification passed.");
