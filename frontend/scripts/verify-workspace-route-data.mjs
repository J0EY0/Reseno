import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { evaluateTypeScript } from "./typescript-module.mjs";

const frontendRoot = new URL("../", import.meta.url);
const modulePath = new URL("src/lib/workspace-route-data.ts", frontendRoot);
const source = await readFile(modulePath, "utf8");
const { getWorkspaceRouteDataPath } = evaluateTypeScript(source);
const expectedPaths = {
  "resume-gallery": "/api/workspace/pages/resumes",
  "resume-detail": "/api/workspace/pages/resume-editor",
  "template-gallery": "/api/workspace/pages/templates",
  "template-detail": "/api/workspace/pages/templates",
  trash: "/api/workspace/pages/trash",
  models: "/api/workspace/pages/models",
  settings: "/api/workspace/pages/settings",
  "pdf-export": "/api/workspace/pages/templates",
};

for (const [routeKind, expectedPath] of Object.entries(expectedPaths)) {
  const actualPath = getWorkspaceRouteDataPath(routeKind);

  if (actualPath !== expectedPath) {
    throw new Error(
      `Workspace route ${routeKind} used ${actualPath}; expected ${expectedPath}.`,
    );
  }
}

const [apiClientSource, workspaceApiSource, resumeTypesSource] =
  await Promise.all([
    readFile(new URL("src/lib/api-client.ts", frontendRoot), "utf8"),
    readFile(new URL("src/lib/workspace-api.ts", frontendRoot), "utf8"),
    readFile(new URL("src/types/resume.ts", frontendRoot), "utf8"),
  ]);
const routeOwnerSources = new Map(
  await Promise.all(
    [
      [
        "resume-gallery",
        "src/components/workspace/use-resume-gallery-workspace.ts",
      ],
      [
        "resume-detail",
        "src/components/workspace/workspace-route-preparation.ts",
      ],
      [
        "template-gallery",
        "src/components/workspace/use-template-gallery-workspace.ts",
      ],
      [
        "template-detail",
        "src/components/workspace/workspace-route-preparation.ts",
      ],
      ["trash", "src/components/workspace/use-trash-workspace.ts"],
      ["models", "src/components/workspace/use-workspace-preferences-route.ts"],
      [
        "settings",
        "src/components/workspace/use-workspace-preferences-route.ts",
      ],
    ].map(async ([kind, path]) => [
      kind,
      await readFile(new URL(path, frontendRoot), "utf8"),
    ]),
  ),
);
const routeOwnerSource = [...routeOwnerSources.values()].join("\n");

if (
  apiClientSource.includes('workspaceBootstrap: "/api/workspace/bootstrap"')
) {
  throw new Error("The generic workspace bootstrap endpoint must be removed.");
}

if (
  /fetchWorkspaceBootstrap|WorkspaceBootstrapScope/.test(workspaceApiSource)
) {
  throw new Error(
    "The frontend must load explicit route data, not bootstrap scopes.",
  );
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

if (/hasWorkspaceField|keyof WorkspacePayload/.test(routeOwnerSource)) {
  throw new Error(
    "Route owners must apply discriminated results, not probe optional fields.",
  );
}

if (!/interface WorkspaceRouteDataMap/.test(source)) {
  throw new Error("Workspace route kinds must map to explicit response DTOs.");
}

if (
  !/getWorkspaceRouteDataPath\(\s*routeKind:\s*LoadableWorkspaceRouteDataKind/.test(
    source,
  )
) {
  throw new Error("Only loadable workspace routes may resolve API paths.");
}

for (const requiredContract of [
  /resumes:\s*ResumeWorkspaceItem\[\]/,
  /defaultTemplateIds:\s*DefaultTemplateIds/,
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

for (const [kind, ownerSource] of routeOwnerSources) {
  const expectedCall = new RegExp(
    `fetchWorkspacePageData\\(\\s*${kind === "models" || kind === "settings" ? "kind" : `"${kind}"`}`,
  );

  if (!expectedCall.test(ownerSource)) {
    throw new Error(
      `Workspace route ${kind} must be read by its owning controller.`,
    );
  }
}

const preparationSource = await readFile(
  new URL(
    "src/components/workspace/workspace-route-preparation.ts",
    frontendRoot,
  ),
  "utf8",
);
let entryDependencies;
const { prepareWorkspaceEntry } = evaluateTypeScript(preparationSource, {
  imports: {
    "@/lib/api-client": {
      isAbortError: (error) => error?.name === "AbortError",
    },
    "@/lib/template-presets": {},
    "@/lib/workspace-api": {
      fetchWorkspaceRouteData: (...args) => entryDependencies.fetch(...args),
    },
    "@/components/preview/document-canvas-loader": {},
    "@/components/workspace/workspace-route-loaders": {
      preloadWorkspaceRoute: (...args) => entryDependencies.preload(...args),
    },
  },
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, reject, resolve };
}

for (const [view, routeKind] of [
  ["resume", "resume-gallery"],
  ["settings", "settings"],
]) {
  const controller = new AbortController();
  const routeModule = deferred();
  const routeData = deferred();
  const events = [];
  const data = { theme: "dark", payload: view };
  let prepared = false;
  entryDependencies = {
    preload(actualView) {
      assert.equal(actualView, view);
      events.push("module");
      return routeModule.promise;
    },
    fetch(actualKind, options) {
      assert.equal(actualKind, routeKind);
      assert.equal(options.signal, controller.signal);
      assert.equal(options.notifyOnError, false);
      events.push("data");
      return routeData.promise;
    },
  };
  const entering = prepareWorkspaceEntry(view, {
    signal: controller.signal,
  }).then((result) => {
    prepared = true;
    return result;
  });
  assert.deepEqual(
    events,
    ["module", "data"],
    "Entry resources must begin loading together.",
  );
  routeData.resolve({ kind: routeKind, data });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(
    prepared,
    false,
    "Page data alone must not publish an unready route entry.",
  );
  routeModule.resolve();
  const result = await entering;
  assert.equal(result.view, view);
  assert.deepEqual(JSON.parse(JSON.stringify(result.data)), data);
  assert.deepEqual(
    Object.keys(result).sort(),
    ["data", "view"],
    "Entry preparation must leave history-token allocation to the final auth commit.",
  );
}

for (const failure of ["cancelled", "failed"]) {
  const controller = new AbortController();
  const routeData = deferred();
  const error = new Error("Page preparation failed");
  entryDependencies = {
    preload: async () => {},
    fetch: () => routeData.promise,
  };
  const entering = prepareWorkspaceEntry("resume", {
    signal: controller.signal,
  });
  if (failure === "cancelled") {
    controller.abort();
    routeData.resolve({ kind: "resume-gallery", data: {} });
    await assert.rejects(entering, { name: "AbortError" });
  } else {
    routeData.reject(error);
    await assert.rejects(entering, (reason) => reason === error);
  }
}

for (const versionOutcome of ["success", "failed", "aborted"]) {
  const flush = deferred();
  const routeRequest = deferred();
  const detailRequest = deferred();
  const versionsRequest = deferred();
  const controller = new AbortController();
  const calls = [];
  const routeData = { customTemplates: [], modelConfigs: [], theme: "dark" };
  const detail = {
    resume: { id: "resume-1" },
    versionId: "version-1",
    savedAt: "now",
  };
  const versions = [{ versionId: "version-1", savedAt: "now" }];
  const record = (kind, request) => (id, options) => {
    calls.push(kind);
    assert.equal(id, kind === "route" ? "resume-detail" : "resume-1");
    assert.equal(options.signal, controller.signal);
    assert.equal(options.notifyOnError, false);
    return request.promise;
  };
  const { loadResumeDetailRouteData } = evaluateTypeScript(preparationSource, {
    imports: {
      "@/lib/api-client": {
        isAbortError: (error) => error?.name === "AbortError",
      },
      "@/lib/template-presets": {},
      "@/lib/workspace-api": {
        fetchWorkspaceRouteData: record("route", routeRequest),
        fetchResumeApi: record("detail", detailRequest),
        fetchResumeVersionsApi: record("versions", versionsRequest),
      },
      "@/components/preview/document-canvas-loader": {},
      "@/components/workspace/workspace-route-loaders": {},
    },
  });
  const result = loadResumeDetailRouteData(
    "resume-1",
    {
      flush: () => flush.promise,
      prepareRead: async () => (accepted) => assert.equal(accepted, routeData),
    },
    { signal: controller.signal },
  );
  assert.deepEqual(calls, [], "Detail reads must wait for queued preferences.");
  flush.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(
    calls.sort(),
    ["detail", "route", "versions"],
    "All three detail resources must start without awaiting another response.",
  );
  routeRequest.resolve({ kind: "resume-detail", data: routeData });
  detailRequest.resolve(detail);
  if (versionOutcome === "success") versionsRequest.resolve({ versions });
  else
    versionsRequest.reject(
      versionOutcome === "aborted"
        ? new DOMException("Cancelled", "AbortError")
        : new Error("History unavailable"),
    );
  if (versionOutcome === "aborted") {
    await assert.rejects(result, (error) => error.name === "AbortError");
  } else {
    const loaded = await result;
    assert.equal(loaded.detail, detail);
    assert.equal(loaded.routeData, routeData);
    assert.deepEqual(
      JSON.parse(JSON.stringify(loaded.versions)),
      versionOutcome === "success" ? versions : [],
    );
  }
}

console.log(
  "Workspace route endpoints and prepared authentication entry verified.",
);
