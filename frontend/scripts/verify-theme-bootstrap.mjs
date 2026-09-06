import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

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
  /<script data-resumate-theme-bootstrap>([\s\S]*?)<\/script>/,
);
assert(bootstrapMatch, "index.html must synchronously bootstrap the saved theme.");

const bootstrapIndex = bootstrapMatch.index ?? -1;
const entryIndex = indexSource.indexOf(
  '<script type="module" src="/src/main.tsx"></script>',
);
assert(
  bootstrapIndex >= 0 && entryIndex > bootstrapIndex,
  "The theme bootstrap must execute before the application module.",
);

function executeBootstrap({
  savedTheme,
  systemDark = false,
  storageError = false,
}) {
  const classes = new Set();
  const documentElement = {
    classList: {
      contains: (value) => classes.has(value),
      toggle(value, force) {
        if (force) {
          classes.add(value);
        } else {
          classes.delete(value);
        }
      },
    },
    style: {},
  };
  const context = {
    document: { documentElement },
    localStorage: {
      getItem() {
        if (storageError) {
          throw new Error("Storage is unavailable.");
        }
        return savedTheme;
      },
    },
    window: {
      matchMedia: () => ({ matches: systemDark }),
    },
  };

  vm.runInNewContext(bootstrapMatch[1], context);
  return {
    colorScheme: documentElement.style.colorScheme,
    dark: classes.has("dark"),
  };
}

assert.deepEqual(executeBootstrap({ savedTheme: "dark" }), {
  colorScheme: "dark",
  dark: true,
});
assert.deepEqual(executeBootstrap({ savedTheme: "light" }), {
  colorScheme: "light",
  dark: false,
});
assert.deepEqual(
  executeBootstrap({ savedTheme: "system", systemDark: true }),
  { colorScheme: "dark", dark: true },
);
assert.deepEqual(
  executeBootstrap({ savedTheme: "system", systemDark: false }),
  { colorScheme: "light", dark: false },
);
assert.deepEqual(executeBootstrap({ savedTheme: "invalid" }), {
  colorScheme: "light",
  dark: false,
});
assert.deepEqual(
  executeBootstrap({ savedTheme: "dark", storageError: true }),
  { colorScheme: "light", dark: false },
);

assert(
  themeSource.includes(
    'workspaceThemePreferenceKey = "resumate-theme"',
  ) && themeSource.includes("loadWorkspaceThemePreference"),
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
    !/loadWorkspaceThemePreference|applyWorkspaceTheme|prefers-color-scheme/.test(detailSource),
    "Detail routes must consume the shared theme without a second bootstrap or system-theme listener.",
  );
}

console.log("theme bootstrap contract verified.");
