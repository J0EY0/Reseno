import { readFile } from "node:fs/promises";
import vm from "node:vm";
import * as ts from "typescript";

const frontendRoot = new URL("../", import.meta.url);
const modulePath = new URL(
  "src/lib/workspace-route-data.ts",
  frontendRoot,
);
const source = await readFile(modulePath, "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const module = { exports: {} };

vm.runInNewContext(compiled, {
  exports: module.exports,
  module,
});

const { getWorkspaceRouteDataPath } = module.exports;
const expectedPaths = {
  "resume-gallery": "/api/workspace/pages/resumes",
  "resume-detail": "/api/workspace/pages/resume-editor",
  "template-gallery": "/api/workspace/pages/templates",
  "template-detail": "/api/workspace/pages/templates",
  trash: "/api/workspace/pages/trash",
  models: "/api/workspace/pages/models",
  settings: "/api/workspace/pages/settings",
  "pdf-export": "/api/workspace/pages/templates",
  unknown: null,
};

for (const [routeKind, expectedPath] of Object.entries(expectedPaths)) {
  const actualPath = getWorkspaceRouteDataPath(routeKind);

  if (actualPath !== expectedPath) {
    throw new Error(
      `Workspace route ${routeKind} used ${actualPath}; expected ${expectedPath}.`,
    );
  }
}

const [apiClientSource, workspaceApiSource, builderSource, resumeTypesSource] =
  await Promise.all([
    readFile(new URL("src/lib/api-client.ts", frontendRoot), "utf8"),
    readFile(new URL("src/lib/workspace-api.ts", frontendRoot), "utf8"),
    readFile(
      new URL("src/components/resume-builder.tsx", frontendRoot),
      "utf8",
    ),
    readFile(new URL("src/types/resume.ts", frontendRoot), "utf8"),
  ]);

if (apiClientSource.includes('workspaceBootstrap: "/api/workspace/bootstrap"')) {
  throw new Error("The generic workspace bootstrap endpoint must be removed.");
}

if (/fetchWorkspaceBootstrap|WorkspaceBootstrapScope/.test(workspaceApiSource)) {
  throw new Error("The frontend must load explicit route data, not bootstrap scopes.");
}

if (
  /fetch(?:Deleted)?ResumesApi|fetch(?:Deleted)?TemplatesApi/.test(
    workspaceApiSource,
  )
) {
  throw new Error(
    "Route initialization must not keep alternate active/deleted list GET helpers.",
  );
}

if (/interface WorkspacePayload/.test(resumeTypesSource)) {
  throw new Error(
    "Route data must not share one all-optional WorkspacePayload contract.",
  );
}

if (/hasWorkspaceField|keyof WorkspacePayload/.test(builderSource)) {
  throw new Error(
    "ResumeBuilder must apply a discriminated route result, not probe optional fields.",
  );
}

if (!/interface WorkspaceRouteDataMap/.test(source)) {
  throw new Error("Workspace route kinds must map to explicit response DTOs.");
}

for (const requiredContract of [
  /resumes:\s*ResumeWorkspaceItem\[\]/,
  /customTemplates:\s*ResumeTemplateDefinition\[\]/,
  /deletedResumes:\s*DeletedResumeWorkspaceItem\[\]/,
  /deletedTemplates:\s*DeletedResumeTemplateDefinition\[\]/,
  /modelConfigs:\s*ModelConfig\[\]/,
  /agentSettings:\s*AgentSettings/,
]) {
  if (!requiredContract.test(source)) {
    throw new Error("Workspace route DTO fields must be required.");
  }
}

if (!/Promise<WorkspaceRouteDataResult<Kind>>/.test(workspaceApiSource)) {
  throw new Error(
    "fetchWorkspaceRouteData must preserve the route kind in its result type.",
  );
}

if (!/switch\s*\(workspaceSource\.kind\)/.test(builderSource)) {
  throw new Error("ResumeBuilder must exhaustively switch on the route data kind.");
}

if (!/signal:\s*options\.signal/.test(apiClientSource)) {
  throw new Error("requestApi must forward AbortSignal to Axios.");
}

if (
  !/if \(isAbortError\(error\)\) \{\s*return Promise\.reject\(error\)/.test(
    apiClientSource,
  )
) {
  throw new Error("Axios cancellation must bypass API error conversion and Toasts.");
}

console.log("Workspace route data endpoints verified.");
