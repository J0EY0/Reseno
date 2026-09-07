import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { evaluateTypeScript } from "./typescript-module.mjs";

const frontendRoot = new URL("../", import.meta.url);
const readText = (path) => readFile(new URL(path, frontendRoot), "utf8");

const programmaticViteScripts = [
  "scripts/verify-api-client.mjs",
  "scripts/verify-auth-setup.mjs",
  "scripts/verify-contact-links.mjs",
  "scripts/verify-model-config-boundaries.mjs",
  "scripts/verify-pdf-resume-import.mjs",
  "scripts/verify-resume-agent-edits.mjs",
  "scripts/verify-resume-sections.mjs",
  "scripts/verify-workspace-architecture.mjs",
];

const [
  recoverySource,
  errorPageSource,
  appSource,
  mainSource,
  viteConfigSource,
  viteTestCacheSource,
  browserFixturesSource,
  resumeGalleryPageSource,
  templateGalleryPageSource,
  ...viteScriptSources
] = await Promise.all([
  readText("src/lib/dynamic-import-recovery.ts"),
  readText("src/components/app-route-error-page.tsx"),
  readText("src/App.tsx"),
  readText("src/main.tsx"),
  readText("vite.config.ts"),
  readText("scripts/vite-test-cache.mjs"),
  readText("../backend/tests/e2e/conftest.py"),
  readText("src/components/workspace/resume-gallery-workspace-page.tsx"),
  readText("src/components/workspace/template-gallery-workspace-page.tsx"),
  ...programmaticViteScripts.map(readText),
]);

const listeners = new Map();
const storage = new Map();
let reloadCount = 0;
const windowMock = {
  addEventListener(type, listener) {
    listeners.set(type, listener);
  },
  location: {
    hash: "",
    pathname: "/models",
    reload() {
      reloadCount += 1;
    },
    search: "",
  },
  removeEventListener(type, listener) {
    if (listeners.get(type) === listener) {
      listeners.delete(type);
    }
  },
  sessionStorage: {
    getItem(key) {
      return storage.get(key) ?? null;
    },
    removeItem(key) {
      storage.delete(key);
    },
    setItem(key, value) {
      storage.set(key, String(value));
    },
  },
};

const {
  clearDynamicImportReloadGuard,
  getApplicationRouteErrorDetails,
  installDynamicImportRecovery,
  isDynamicImportFailure,
  tryReloadAfterDynamicImportFailure,
} = evaluateTypeScript(recoverySource, {
  globals: { window: windowMock },
});

assert.deepEqual(
  { ...getApplicationRouteErrorDetails(new Error("ordinary render failure")) },
  { kind: "unexpected", message: "ordinary render failure" },
  "Ordinary render failures must never be mislabeled as missing assets.",
);
assert.deepEqual(
  {
    ...getApplicationRouteErrorDetails(
      new TypeError("Failed to fetch dynamically imported module: /route.js"),
    ),
  },
  {
    kind: "dynamic-import",
    message: "Failed to fetch dynamically imported module: /route.js",
  },
);
assert.deepEqual(
  {
    ...getApplicationRouteErrorDetails({
      data: "Workspace loader failed",
      status: 500,
      statusText: "Internal Server Error",
    }),
  },
  { kind: "unexpected", message: "Workspace loader failed" },
  "React Router error responses should preserve their useful detail without being mislabeled as chunk failures.",
);

assert.equal(
  isDynamicImportFailure(
    new TypeError(
      "Failed to fetch dynamically imported module: /models-workspace-page.js",
    ),
  ),
  true,
);
assert.equal(isDynamicImportFailure(new Error("ordinary render failure")), false);

const uninstall = installDynamicImportRecovery();
const preloadErrorListener = listeners.get("vite:preloadError");
assert.equal(typeof preloadErrorListener, "function");

function dispatchPreloadError() {
  let defaultPrevented = false;
  preloadErrorListener({
    payload: new TypeError("Failed to fetch dynamically imported module"),
    preventDefault() {
      defaultPrevented = true;
    },
  });
  return defaultPrevented;
}

assert.equal(dispatchPreloadError(), true);
assert.equal(reloadCount, 1, "The first failure should reload exactly once.");
assert.equal(dispatchPreloadError(), false);
assert.equal(
  reloadCount,
  1,
  "The same route must not enter an automatic reload loop.",
);
windowMock.location.search = "?retry=1";
assert.equal(dispatchPreloadError(), false);
assert.equal(
  reloadCount,
  1,
  "Changing a query must not bypass the route's reload guard.",
);

windowMock.location.pathname = "/settings";
assert.equal(
  tryReloadAfterDynamicImportFailure(
    new TypeError("Importing a module script failed"),
  ),
  true,
);
assert.equal(reloadCount, 2, "A different route gets its own recovery attempt.");
assert.equal(
  tryReloadAfterDynamicImportFailure(new Error("ordinary render failure")),
  false,
);
assert.equal(reloadCount, 2);

clearDynamicImportReloadGuard();
assert.equal(dispatchPreloadError(), true);
assert.equal(
  reloadCount,
  3,
  "A successful route commit must re-arm future recovery.",
);

const storageSetItem = windowMock.sessionStorage.setItem;
windowMock.location.pathname = "/trash";
windowMock.sessionStorage.setItem = () => {
  throw new Error("storage unavailable");
};
assert.equal(
  tryReloadAfterDynamicImportFailure(
    new TypeError("Failed to fetch dynamically imported module"),
  ),
  false,
  "Recovery must not reload when it cannot persist the loop guard.",
);
assert.equal(reloadCount, 3);
windowMock.sessionStorage.setItem = storageSetItem;

uninstall();
assert.equal(listeners.has("vite:preloadError"), false);

assert.match(mainSource, /installDynamicImportRecovery\(\)/);
assert.ok(
  mainSource.indexOf("installDynamicImportRecovery()") <
    mainSource.indexOf("createBrowserRouter(["),
  "The preload-error listener must be installed before route rendering starts.",
);
assert.match(mainSource, /errorElement:\s*<AppRouteErrorPage\s*\/>/);
assert.match(errorPageSource, /useRouteError\(\)/);
assert.match(errorPageSource, /getApplicationRouteErrorDetails\(error\)/);
assert.match(errorPageSource, /tryReloadAfterDynamicImportFailure\(error\)/);
assert.doesNotMatch(
  errorPageSource,
  /clearDynamicImportReloadGuard\(\)/,
  "A manual retry must retain the loop guard until a route commits successfully.",
);
assert.match(errorPageSource, /window\.location\.assign\("\/resume"\)/);
assert.match(errorPageSource, /details\.message/);
assert.match(
  appSource,
  /<Suspense[\s\S]{0,900}\{children\}\s*<DynamicImportRecoveryReset\s*\/>[\s\S]{0,200}<\/Suspense>/,
  "The reload guard reset must render after the lazy child inside resolved Suspense content.",
);
assert.match(appSource, /const appRouteFallback = \([\s\S]{0,240}<Spinner/);
assert.doesNotMatch(
  appSource.slice(
    appSource.indexOf("const appRouteFallback"),
    appSource.indexOf("function DynamicImportRecoveryReset"),
  ),
  /Skeleton/,
  "Only the app-level lazy/auth fallback should use the centered Spinner.",
);
for (const pageSource of [resumeGalleryPageSource, templateGalleryPageSource]) {
  assert.match(
    pageSource,
    /!\w+\.hasLoaded[\s\S]{0,160}<GalleryRouteSkeleton/,
    "Gallery data loading must keep its route-specific skeleton.",
  );
}

assert.match(viteConfigSource, /RESUMATE_VITE_CACHE_DIR/);
assert.match(viteConfigSource, /cacheDir/);
assert.match(viteTestCacheSource, /mkdtempSync/);
assert.match(viteTestCacheSource, /tmpdir\(\)/);
assert.match(browserFixturesSource, /"RESUMATE_VITE_CACHE_DIR"/);

for (const [index, source] of viteScriptSources.entries()) {
  assert.match(
    source,
    /createViteTestCacheDir/,
    `${programmaticViteScripts[index]} must use the shared cache isolator.`,
  );
  assert.match(
    source,
    /cacheDir:\s*createViteTestCacheDir\(\)/,
    `${programmaticViteScripts[index]} must assign an isolated Vite cache.`,
  );
  assert.match(
    source,
    /optimizeDeps:\s*\{\s*noDiscovery:\s*true\s*\}/,
    `${programmaticViteScripts[index]} must not start an unused dependency scan.`,
  );
}

console.log("Dynamic import recovery and Vite cache isolation verified.");
