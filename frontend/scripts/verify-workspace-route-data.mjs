import { readFile } from "node:fs/promises";

const frontendRoot = new URL("../", import.meta.url);
const modulePath = new URL("src/lib/workspace-route-data.ts", frontendRoot);
const source = await readFile(modulePath, "utf8");
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
