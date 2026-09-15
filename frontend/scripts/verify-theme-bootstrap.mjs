import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const projectRoot = new URL("../", import.meta.url);
const [
  indexSource,
  themeSource,
  persistenceSource,
  providerSource,
  resumeDetailWorkspaceSource,
  templateDetailWorkspaceSource,
] = await Promise.all([
  readFile(new URL("index.html", projectRoot), "utf8"),
  readFile(new URL("src/lib/workspace-theme.ts", projectRoot), "utf8"),
  readFile(
    new URL("src/lib/workspace-preferences-persistence.ts", projectRoot),
    "utf8",
  ),
  readFile(
    new URL("src/components/workspace/workspace-preferences.tsx", projectRoot),
    "utf8",
  ),
  readFile(
    new URL(
      "src/components/workspace/use-resume-detail-workspace.ts",
      projectRoot,
    ),
    "utf8",
  ),
  readFile(
    new URL(
      "src/components/workspace/use-template-detail-workspace.ts",
      projectRoot,
    ),
    "utf8",
  ),
]);

const bootstrapMatch = indexSource.match(
  /<script data-reseno-theme-bootstrap>([\s\S]*?)<\/script>/,
);
assert(
  bootstrapMatch,
  "index.html must synchronously bootstrap the saved theme.",
);

const bootstrapIndex = bootstrapMatch.index ?? -1;
const entryIndex = indexSource.indexOf(
  '<script type="module" src="/src/main.tsx"></script>',
);
assert(
  bootstrapIndex >= 0 && entryIndex > bootstrapIndex,
  "The theme bootstrap must execute before the application module.",
);

assert(
  themeSource.includes('workspaceThemePreferenceKey = "reseno-theme"') &&
    themeSource.includes("loadWorkspaceThemePreference"),
  "The runtime and HTML bootstrap must share the validated theme cache contract.",
);
assert(
  persistenceSource.includes("saveWorkspaceThemePreference"),
  "Workspace preference persistence must update the first-paint theme cache.",
);
assert(
  providerSource.includes("loadWorkspaceThemePreference"),
  "The shared WorkspacePreferencesProvider must initialize from the same theme cache as HTML.",
);
for (const detailSource of [
  resumeDetailWorkspaceSource,
  templateDetailWorkspaceSource,
]) {
  assert(
    !/loadWorkspaceThemePreference|applyWorkspaceTheme|prefers-color-scheme/.test(
      detailSource,
    ),
    "Detail routes must consume the shared theme without a second bootstrap or system-theme listener.",
  );
}

console.log("theme bootstrap contract verified.");
