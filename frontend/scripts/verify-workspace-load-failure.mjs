import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const frontendRoot = new URL("../", import.meta.url);

async function readText(path) {
  return readFile(new URL(path, frontendRoot), "utf8");
}

const [
  zhSource,
  enSource,
  builderSource,
  modelConfigPanelSource,
  modelConfigFormSource,
  modelConfigApiSource,
  agentApiSource,
  copilotPanelSource,
] =
  await Promise.all([
    readText("src/i18n/locales/zh.json"),
    readText("src/i18n/locales/en.json"),
    readText("src/components/resume-builder.tsx"),
    readText("src/components/model-config-panel.tsx"),
    readText("src/components/model-config-form-popover.tsx"),
    readText("src/lib/model-config-api.ts"),
    readText("src/lib/agent-api.ts"),
    readText("src/components/copilot/copilot-panel.tsx"),
  ]);
const zh = JSON.parse(zhSource);
const en = JSON.parse(enSource);

assert.equal(
  zh.loadError,
  zh.apiMessages.REQUEST_FAILED,
  "Chinese request failures must use the canonical request failure message.",
);
assert.equal(
  en.loadError,
  en.apiMessages.REQUEST_FAILED,
  "English request failures must use the canonical request failure message.",
);
assert.doesNotMatch(
  zh.loadError,
  /回退|空白简历/,
  "Request failure copy must not claim that an empty resume was loaded.",
);
assert.doesNotMatch(
  en.loadError,
  /fall(?:ing)? back|empty resume|remote data/i,
  "Request failure copy must not claim that an empty resume was loaded.",
);

assert.match(
  builderSource,
  /const \[hasWorkspaceLoadError, setHasWorkspaceLoadError\] = useState\(false\)/,
  "Route initialization failures must be tracked separately from action failures.",
);
assert.match(
  builderSource,
  /hasWorkspaceLoadError\s*\?[\s\S]{0,40}renderWorkspaceLoadError\(\)/,
  "A failed route initialization must render an error state instead of workspace content.",
);
assert.match(
  builderSource,
  /fetchWorkspaceRouteData\([\s\S]{0,120}notifyOnError:\s*false/,
  "Workspace route data must defer Toast handling to the route loader.",
);
assert.match(
  builderSource,
  /fetchResumeApi\(\s*route\.id,\s*\{[\s\S]{0,100}notifyOnError:\s*false,[\s\S]{0,60}signal,[\s\S]{0,20}\}\s*\)/,
  "Resume detail initialization must defer Toast handling to the route loader.",
);
assert.match(
  builderSource,
  /fetchResumeVersionsApi\(\s*route\.id,\s*\{[\s\S]{0,100}notifyOnError:\s*false,[\s\S]{0,60}signal,[\s\S]{0,20}\}\s*\)/,
  "Resume version initialization must defer Toast handling to the route loader.",
);

const loaderStart = builderSource.indexOf("  const loadWorkspace = useCallback(");
const loaderEnd = builderSource.indexOf("\n  useEffect(() => {", loaderStart);

assert.notEqual(loaderStart, -1, "Workspace loader was not found.");
assert.notEqual(loaderEnd, -1, "Workspace loader boundary was not found.");

const loaderSource = builderSource.slice(loaderStart, loaderEnd);
const loaderCatchStart = loaderSource.indexOf("      } catch (error) {");
const loaderCatchEnd = loaderSource.indexOf("      } finally {", loaderCatchStart);

assert.notEqual(loaderCatchStart, -1, "Workspace loader catch was not found.");
assert.notEqual(loaderCatchEnd, -1, "Workspace loader catch boundary was not found.");

const loaderCatchSource = loaderSource.slice(loaderCatchStart, loaderCatchEnd);

assert.match(
  loaderCatchSource,
  /isAbortError\(error\)[\s\S]*return;[\s\S]*workspaceLoadRequestIdRef/,
  "Cancelled route requests must exit before stale checks and Toast handling.",
);
assert.match(
  loaderCatchSource,
  /workspaceLoadRequestIdRef\.current !== requestId[\s\S]*toast\.error/,
  "Stale route requests must be ignored before any Toast is shown.",
);
assert.match(
  loaderCatchSource,
  /id:\s*"workspace-load-error"/,
  "Route initialization failures must reuse one stable Toast id.",
);
assert.match(
  loaderCatchSource,
  /setHasWorkspaceLoadError\(true\)/,
  "Workspace request failures must enter the route error state.",
);
assert.match(
  loaderCatchSource,
  /apiMessages\s*\.\s*REQUEST_FAILED/,
  "Every route initialization Toast must use the canonical request failure message.",
);
assert.doesNotMatch(
  loaderCatchSource,
  /\.loadError/,
  "Route initialization must not reuse legacy resume-loading copy.",
);

assert.match(
  builderSource,
  /const controller = new AbortController\(\);[\s\S]{0,600}window\.setTimeout[\s\S]{0,200}loadWorkspace\(controller\.signal\)[\s\S]{0,300}clearTimeout\(loadTimer\)[\s\S]{0,100}controller\.abort\(\)/,
  "Every route load effect must suppress the StrictMode preflight and abort requests during cleanup.",
);
assert.doesNotMatch(
  loaderCatchSource,
  /resetResumeWorkspace|hydrateResumeWorkspace|setResume\(|setResumeDocuments\(/,
  "Workspace request failures must not synthesize or replace resume content.",
);

const routeErrorRendererStart = builderSource.indexOf(
  "  function renderWorkspaceLoadError()",
);
const routeErrorRendererEnd = builderSource.indexOf(
  "\n  function renderTemplateGalleryWorkspace()",
  routeErrorRendererStart,
);
const routeErrorRendererSource = builderSource.slice(
  routeErrorRendererStart,
  routeErrorRendererEnd,
);

assert.doesNotMatch(
  routeErrorRendererSource,
  /t\.(?:apiMessages\.REQUEST_FAILED|loadError)/,
  "The blocked route surface must not duplicate the global request failure Toast.",
);
assert.doesNotMatch(
  routeErrorRendererSource,
  /role=["']alert["']/,
  "The blocked route surface must not announce a second request failure alert.",
);
assert.match(
  routeErrorRendererSource,
  /aria-hidden=["']true["']/,
  "The empty blocked route surface must stay hidden from assistive technology.",
);

assert.match(
  modelConfigPanelSource,
  /if \(!isApiErrorToastShown\(error\)\)/,
  "Model deletion must not show a second Toast after the API client handled the error.",
);

const providerLoadEffectStart = modelConfigFormSource.indexOf(
  "    void getModelProviders()",
);
const providerLoadEffectEnd = modelConfigFormSource.indexOf(
  "\n  useEffect(() => {",
  providerLoadEffectStart,
);

assert.notEqual(
  providerLoadEffectStart,
  -1,
  "Model provider metadata loader was not found.",
);
assert.notEqual(
  providerLoadEffectEnd,
  -1,
  "Model provider metadata loader boundary was not found.",
);

const providerLoadEffectSource = modelConfigFormSource.slice(
  modelConfigFormSource.lastIndexOf("  useEffect(() => {", providerLoadEffectStart),
  providerLoadEffectEnd,
);

assert.match(
  providerLoadEffectSource,
  /if \(!open\b[^)]*\)\s*\{\s*return;/,
  "/models must not request provider metadata before the create/edit dialog opens.",
);
assert.match(
  providerLoadEffectSource,
  /\}, \[[^\]]*\bopen\b[^\]]*\]\);/,
  "Opening the model dialog must trigger the deferred provider metadata request.",
);
assert.match(
  modelConfigApiSource,
  /apiRoutes\.modelProviders,[\s\S]{0,80}notifyOnError:\s*false/,
  "Model provider metadata failures must stay inside the dialog instead of showing a second global Toast.",
);

const agentSessionLoaderSource = agentApiSource.slice(
  agentApiSource.indexOf("export async function loadAgentSession"),
  agentApiSource.indexOf("export async function replaceAgentSession"),
);

assert.match(
  agentSessionLoaderSource,
  /signal\?: AbortSignal[\s\S]*signal: options\.signal/,
  "Agent session reads must accept the owning panel's cancellation signal.",
);
assert.match(
  copilotPanelSource,
  /loadAgentSession\(resumeId,\s*\{\s*signal: abortController\.signal,?\s*\}\)/,
  "Copilot cleanup must cancel StrictMode's stale session read.",
);

console.log("Workspace load failure behavior verified.");
