import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import * as ts from "typescript";

const frontendRoot = new URL("../", import.meta.url);

async function readText(path) {
  return readFile(new URL(path, frontendRoot), "utf8");
}

const [
  zhSource,
  enSource,
  resumeDetailLoaderSource,
  resumeDetailViewSource,
  workspaceRouteErrorSource,
  workspaceLoadErrorSource,
  workspaceRoutePreparationSource,
  templateDetailRouteSource,
  modelConfigPanelSource,
  modelConfigPopoverSource,
  modelConfigDialogControllerSource,
  modelConfigApiSource,
  agentSessionRunClientSource,
  agentSessionHydrationSource,
] =
  await Promise.all([
    readText("src/i18n/locales/zh.json"),
    readText("src/i18n/locales/en.json"),
    readText("src/components/workspace/use-resume-detail-loader.ts"),
    readText("src/components/workspace/resume-detail-workspace-view.tsx"),
    readText("src/components/workspace/workspace-route-error.tsx"),
    readText("src/lib/workspace-load-error.ts"),
    readText("src/components/workspace/workspace-route-preparation.ts"),
    readText("src/components/workspace/use-template-detail-workspace.ts"),
    readText("src/components/model-config-panel.tsx"),
    readText("src/components/model-config-form-popover.tsx"),
    readText("src/components/models/use-model-config-dialog.ts"),
    readText("src/lib/model-config-api.ts"),
    readText("src/lib/agent-session-run-client.ts"),
    readText("src/components/copilot/use-agent-session-hydration.ts"),
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
assert.equal(zh.retry, "重试", "Chinese workspace errors need a retry action.");
assert.equal(en.retry, "Retry", "English workspace errors need a retry action.");
assert.equal(zh.contentNotLoaded, "当前内容未加载");
assert.equal(en.contentNotLoaded, "Content isn't loaded");
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
  resumeDetailLoaderSource,
  /const \[hasLoadError, setHasLoadError\] = useState\(false\)/,
  "Route initialization failures must be tracked separately from action failures.",
);
assert.match(
  templateDetailRouteSource,
  /const \[hasLoadError, setHasLoadError\] = useState\(false\)/,
  "Template-detail initialization failures must remain route-owned.",
);
assert.match(
  workspaceRoutePreparationSource,
  /fetchWorkspacePageData\("template-detail",\s*persistence,\s*\{[\s\S]{0,100}notifyOnError:\s*false,[\s\S]{0,60}signal/,
  "Template detail must defer Toast handling to its route loader.",
);
assert.match(
  templateDetailRouteSource,
  /isAbortError\(error\)[\s\S]{0,160}requestIdRef\.current !== requestId[\s\S]*!isApiErrorToastShown\(error\)[\s\S]*showWorkspaceLoadError\([\s\S]*apiMessages[\s\S]*REQUEST_FAILED[\s\S]*setHasLoadError\(true\)/,
  "Template detail must ignore cancelled and stale reads before one canonical failure Toast.",
);
assert.match(
  templateDetailRouteSource,
  /new AbortController\(\)[\s\S]{0,500}window\.setTimeout[\s\S]{0,300}controller\.abort\(\)/,
  "Template detail must suppress StrictMode preflight and abort stale reads.",
);
assert.match(
  resumeDetailViewSource,
  /state\.hasLoadError\s*\?[\s\S]{0,160}<WorkspaceRouteError/,
  "A failed route initialization must render an error state instead of workspace content.",
);
assert.match(
  workspaceRoutePreparationSource,
  /fetchWorkspacePageData\("resume-detail",\s*persistence,[\s\S]{0,120}notifyOnError:\s*false/,
  "Workspace route data must defer Toast handling to the route loader.",
);
assert.match(
  workspaceRoutePreparationSource,
  /fetchResumeApi\(\s*resumeId,\s*\{[\s\S]{0,100}notifyOnError:\s*false,[\s\S]{0,60}signal,[\s\S]{0,20}\}\s*\)/,
  "Resume detail initialization must defer Toast handling to the route loader.",
);
assert.match(
  workspaceRoutePreparationSource,
  /fetchResumeVersionsApi\(\s*resumeId,\s*\{[\s\S]{0,100}notifyOnError:\s*false,[\s\S]{0,60}signal,[\s\S]{0,20}\}\s*\)/,
  "Resume version initialization must defer Toast handling to the route loader.",
);

const loaderSource = resumeDetailLoaderSource;
const loaderCatchStart = loaderSource.indexOf("      } catch (error) {");
const loaderCatchEnd = loaderSource.indexOf("      } finally {", loaderCatchStart);

assert.notEqual(loaderCatchStart, -1, "Workspace loader catch was not found.");
assert.notEqual(loaderCatchEnd, -1, "Workspace loader catch boundary was not found.");

const loaderCatchSource = loaderSource.slice(loaderCatchStart, loaderCatchEnd);

assert.match(
  loaderCatchSource,
  /isAbortError\(error\)[\s\S]*requestIdRef\.current !== requestId[\s\S]*return;/,
  "Cancelled route requests must exit before stale checks and Toast handling.",
);
assert.match(
  loaderCatchSource,
  /requestIdRef\.current !== requestId[\s\S]*showWorkspaceLoadError\(/,
  "Stale route requests must be ignored before any Toast is shown.",
);
assert.match(
  loaderCatchSource,
  /if \(!isApiErrorToastShown\(error\)\) \{\s*showWorkspaceLoadError\(/,
  "Route initialization must show its own error only when the API client has not already shown it.",
);
assert.match(
  loaderSource,
  /dismissWorkspaceLoadError\(\)/,
  "Retrying a workspace load must dismiss the stale error Toast.",
);

const toastEvents = [];
const visibleToasts = new Map([["unrelated", "Saved successfully"]]);
let nextToastId = 0;
const loadErrorModule = { exports: {} };
vm.runInNewContext(ts.transpileModule(workspaceLoadErrorSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, {
  module: loadErrorModule,
  exports: loadErrorModule.exports,
  require(specifier) {
    assert.equal(specifier, "sonner");
    return { toast: {
      error(message, options) {
        assert.deepEqual({ ...options }, { closeButton: true }, "Each failure must let Sonner allocate a fresh Toast ID.");
        const id = nextToastId++;
        visibleToasts.set(id, message);
        toastEvents.push(`show:${id}`);
        return id;
      },
      dismiss(id) {
        assert.notEqual(id, undefined, "Dismissing a route error must never dismiss every Toast.");
        visibleToasts.delete(id);
        toastEvents.push(`dismiss:${id}`);
      },
    } };
  },
});
const { dismissWorkspaceLoadError, showWorkspaceLoadError } = loadErrorModule.exports;
dismissWorkspaceLoadError();
dismissWorkspaceLoadError();
assert.deepEqual(toastEvents, [], "Dismissing an absent route error must be a no-op.");
for (let attempt = 0; attempt < 3; attempt += 1) {
  showWorkspaceLoadError("Request failed");
  dismissWorkspaceLoadError();
  dismissWorkspaceLoadError();
}
assert.deepEqual(toastEvents, ["show:0", "dismiss:0", "show:1", "dismiss:1", "show:2", "dismiss:2"],
  "Immediate repeated failures must receive new IDs, and each error may be dismissed only once.");
showWorkspaceLoadError("First route failed");
showWorkspaceLoadError("Second route failed");
assert.deepEqual(toastEvents.slice(-3), ["show:3", "dismiss:3", "show:4"],
  "Replacing a route error must dismiss only the previous error before showing the next one.");
assert.deepEqual([...visibleToasts], [["unrelated", "Saved successfully"], [4, "Second route failed"]]);
dismissWorkspaceLoadError();
dismissWorkspaceLoadError();
assert.deepEqual([...visibleToasts], [["unrelated", "Saved successfully"]],
  "Repeated route cleanup must preserve unrelated Toasts.");
assert.match(
  loaderCatchSource,
  /setHasLoadError\(true\)/,
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
  resumeDetailLoaderSource,
  /const controller = new AbortController\(\);[\s\S]{0,600}window\.setTimeout[\s\S]{0,200}load\(controller\.signal\)[\s\S]{0,300}clearTimeout\(loadTimer\)[\s\S]{0,100}controller\.abort\(\)/,
  "Every route load effect must suppress the StrictMode preflight and abort requests during cleanup.",
);
assert.doesNotMatch(
  loaderCatchSource,
  /onLoadRef\.current\(|setResume\(|setResumeDocuments\(/,
  "Workspace request failures must not synthesize or replace resume content.",
);

assert.doesNotMatch(
  workspaceRouteErrorSource,
  /messages\.loadError/,
  "The blocked route surface must not duplicate the request failure Toast.",
);
assert.doesNotMatch(
  workspaceRouteErrorSource,
  /role=["']alert["']/,
  "The recovery surface is not a second error alert.",
);
assert.match(
  workspaceRouteErrorSource,
  /messages\.contentNotLoaded/,
  "The blocked route surface must describe its neutral recovery state.",
);
assert.match(
  workspaceRouteErrorSource,
  /onRetry[\s\S]*messages\.retry/,
  "The blocked route surface must provide an explicit retry action.",
);
assert.match(
  resumeDetailLoaderSource,
  /\[load, retryKey\]/,
  "Retrying must reuse the abortable workspace loading effect.",
);

assert.match(
  modelConfigPanelSource,
  /if \(!isApiErrorToastShown\(error\)\)/,
  "Model deletion must not show a second Toast after the API client handled the error.",
);

assert.match(
  modelConfigPopoverSource,
  /import\s*\{\s*ModelConfigDialog\s*\}\s*from\s*["']@\/components\/models\/model-config-dialog["']/,
  "/models must include the dialog in its already-lazy route chunk so first open has one stable surface.",
);
assert.match(
  modelConfigPopoverSource,
  /const \[dialogSession, setDialogSession\] = useState<number \| null>\([\s\S]*?defaultOpen \? 1 : null[\s\S]*?\)[\s\S]*\{dialogSession !== null \? \([\s\S]*?<ModelConfigDialog/,
  "/models must not mount the provider loader before the dialog opens and must retain it for the exit animation.",
);
assert.match(
  modelConfigDialogControllerSource,
  /useEffect\(\(\) => \{[\s\S]*void getModelProviders\(\)/,
  "The mounted dialog controller must request provider metadata.",
);
assert.match(
  modelConfigApiSource,
  /apiRoutes\.modelProviders,[\s\S]{0,80}notifyOnError:\s*false/,
  "Model provider metadata failures must stay inside the dialog instead of showing a second global Toast.",
);

const agentSessionLoaderSource = agentSessionRunClientSource.slice(
  agentSessionRunClientSource.indexOf("export async function loadAgentSession"),
  agentSessionRunClientSource.indexOf(
    "export async function replaceAgentSession",
  ),
);
const activeAgentRunLoaderSource = agentSessionRunClientSource.slice(
  agentSessionRunClientSource.indexOf("export function loadActiveAgentRun"),
  agentSessionRunClientSource.indexOf("export function stopAgentRun"),
);

assert.match(
  agentSessionLoaderSource,
  /notifyOnError\?: boolean[\s\S]*signal\?: AbortSignal[\s\S]*notifyOnError: options\.notifyOnError[\s\S]*signal: options\.signal/,
  "Agent session reads must forward caller-owned cancellation and notification policy.",
);
assert.match(
  activeAgentRunLoaderSource,
  /notifyOnError\?: boolean[\s\S]*signal\?: AbortSignal[\s\S]*notifyOnError: options\.notifyOnError[\s\S]*signal: options\.signal/,
  "Active Agent run reads must forward caller-owned cancellation and notification policy.",
);
assert.match(
  agentSessionHydrationSource,
  /loadAgentSession\(resumeId,\s*\{\s*notifyOnError: false,\s*signal: abortController\.signal,?\s*\}\)/,
  "Copilot hydration must silently cancel or surface its session read locally.",
);
assert.match(
  agentSessionHydrationSource,
  /loadActiveAgentRun\(resumeId,\s*\{\s*notifyOnError: false,\s*signal: abortController\.signal,?\s*\}\)/,
  "Copilot hydration must silently cancel or surface its active-run read locally.",
);

console.log("Workspace load failure behavior verified.");
