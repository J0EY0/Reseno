import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const root = new URL("../", import.meta.url);
const [main, config, fixtures] = await Promise.all(
  ["src/main.tsx", "vite.config.ts", "../backend/tests/e2e/conftest.py"].map(
    (path) => readFile(new URL(path, root), "utf8"),
  ),
);
assert.match(main, /errorElement:\s*<AppRouteErrorPage\s*\/>/);
assert.match(config, /RESENO_VITE_CACHE_DIR/);
assert.match(config, /cacheDir/);
assert.match(fixtures, /"RESENO_VITE_CACHE_DIR"/);
console.log("Route error ownership and Vite cache isolation verified.");
