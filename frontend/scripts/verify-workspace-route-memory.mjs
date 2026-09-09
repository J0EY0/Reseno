import assert from "node:assert/strict";
import { loadTypeScriptModule } from "./typescript-module.mjs";

let historyState = null;
let historyUrl = "http://localhost/settings?tab=models#active";
let historyWrites = 0;
const history = {
  get state() {
    return historyState;
  },
  replaceState(state, _unused, url) {
    historyState = structuredClone(state);
    if (url !== undefined) {
      historyUrl = new URL(url, historyUrl).href;
    }
    historyWrites += 1;
  },
};
const handoffs = await loadTypeScriptModule(
  new URL("../src/lib/workspace-route-handoff.ts", import.meta.url),
  { globals: { window: { history } } },
);
const {
  clearWorkspaceRouteMemory,
  createWorkspaceLateralRouteHandoff,
  getWorkspaceLateralRouteHandoff,
  rememberWorkspaceLateralRoute,
  resolveWorkspaceLateralRoute,
} = await loadTypeScriptModule(
  new URL("../src/lib/workspace-route-memory.ts", import.meta.url),
  { imports: { "@/lib/workspace-route-handoff": handoffs } },
);

const resume = {
  data: {
    customTemplates: [],
    defaultTemplateIds: {
      zh: "minimal",
      en: "classic",
    },
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
const currentHistoryState = {
  idx: 3,
  key: "settings-current",
  masked: { pathname: "/workspace" },
  usr: settingsState,
};
historyState = currentHistoryState;
handoffs.clearWorkspaceRouteHistoryState("resume-stale");
assert.equal(
  historyState,
  currentHistoryState,
  "A delayed cleanup from another entry must preserve the current handoff.",
);
assert.equal(historyWrites, 0);

handoffs.clearWorkspaceRouteHistoryState("settings-current");
assert.deepEqual(
  historyState,
  { ...currentHistoryState, usr: null },
  "Consuming the current handoff must preserve Router keys, indices, and metadata.",
);
assert.equal(
  historyUrl,
  "http://localhost/settings?tab=models#active",
  "History cleanup must preserve the current pathname, query, and hash.",
);
assert.equal(currentHistoryState.usr, settingsState);
assert.equal(historyWrites, 1);

handoffs.clearWorkspaceRouteHistoryState("settings-current");
historyState = null;
handoffs.clearWorkspaceRouteHistoryState("settings-current");
assert.equal(historyWrites, 1, "Empty history state must not be rewritten.");

assert.equal(getWorkspaceLateralRouteHandoff(settingsState), settings);
assert.equal(
  getWorkspaceLateralRouteHandoff(settingsState),
  settings,
  "Repeated initial renders must read an active handoff without consuming it.",
);
assert.equal(
  getWorkspaceLateralRouteHandoff({ ...settingsState, view: "resume" }),
  null,
  "A token must not supply preferences for a mismatched destination.",
);
assert.equal(getWorkspaceLateralRouteHandoff(null), null);
assert.equal(
  Object.prototype.hasOwnProperty.call(settingsState, "data"),
  false,
  "Browser history must contain only a small token, never the route DTO.",
);
assert.equal(
  resolveWorkspaceLateralRoute(null, "settings").data,
  settings.data,
  "A successful prepared handoff must publish its target snapshot before commit.",
);

const arrival = resolveWorkspaceLateralRoute(settingsState, "settings");
assert.equal(arrival.data, settings.data);
assert.equal(arrival.shouldScrubHistory, true);
assert.equal(arrival.tokenToDelete, settingsState.token);
handoffs.deleteWorkspaceHandoffToken(arrival.tokenToDelete);

const back = resolveWorkspaceLateralRoute(null, "resume");
assert.equal(
  back.data,
  resume.data,
  "Same-session POP must seed its first frame from the latest committed view snapshot.",
);

const deadToken = resolveWorkspaceLateralRoute(settingsState, "settings");
assert.equal(deadToken.data, settings.data);
assert.equal(
  getWorkspaceLateralRouteHandoff(settingsState),
  null,
  "A consumed token must not recover stale entry preferences from committed page memory.",
);
assert.equal(
  deadToken.shouldScrubHistory,
  true,
  "A consumed token must be removed from browser history.",
);

clearWorkspaceRouteMemory();
assert.equal(resolveWorkspaceLateralRoute(null, "resume").data, null);
const clearedDeadToken = resolveWorkspaceLateralRoute(
  settingsState,
  "settings",
);
assert.equal(clearedDeadToken.data, null);
assert.equal(clearedDeadToken.shouldScrubHistory, true);

const details = await loadTypeScriptModule(
  new URL("../src/lib/workspace-detail-route-handoff.ts", import.meta.url),
  {
    imports: {
      "@/lib/workspace-route-handoff": handoffs,
    },
  },
);
const templateData = {
  customTemplates: [
    {
      id: "custom-a",
      layout: { images: [{ src: "A".repeat(5 * 1024 * 1024) }] },
    },
  ],
  defaultTemplateIds: { zh: "minimal", en: "minimal" },
};
const detailData = {
  detail: { resume: { id: "resume-a" }, savedAt: "now", versionId: "v1" },
  routeData: { ...templateData, modelConfigs: [], agentSettings: {} },
  versions: [],
};
const detailState = details.createResumeDetailRouteHandoff(detailData, 1, 2);
assert.ok(
  JSON.stringify(detailState).length < 256,
  "Resume detail history must not serialize document or template images.",
);
assert.equal(
  details.getResumeDetailRouteHandoff(structuredClone(detailState), "resume-a")
    .payload,
  detailData,
);
assert.equal(
  details.getResumeDetailRouteHandoff(detailState, "another-resume"),
  null,
);
assert.equal(
  details.getResumeDetailRouteHandoff(
    { ...detailState, token: "missing" },
    "resume-a",
  ),
  null,
);
const templateState = details.createTemplateDetailRouteHandoff(
  "custom-a",
  templateData,
  "en",
);
assert.ok(
  JSON.stringify(templateState).length < 256,
  "Template detail history must not serialize the template catalog.",
);
assert.equal(
  details.getTemplateDetailRouteHandoff(
    structuredClone(templateState),
    "custom-a",
  ).data,
  templateData,
);
assert.equal(
  details.getTemplateDetailRouteHandoff(templateState, "another-template"),
  null,
);
handoffs.releaseWorkspaceRouteHandoff(detailState);
assert.equal(
  details.getResumeDetailRouteHandoff(detailState, "resume-a"),
  null,
);
assert.ok(details.getTemplateDetailRouteHandoff(templateState, "custom-a"));
clearWorkspaceRouteMemory();
assert.equal(
  details.getResumeDetailRouteHandoff(detailState, "resume-a"),
  null,
);
assert.equal(
  details.getTemplateDetailRouteHandoff(templateState, "custom-a"),
  null,
);

console.log("Workspace route memory verification passed.");
