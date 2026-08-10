import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const cacheDirectories = new Set();
let cleanupRegistered = false;

function registerCleanup() {
  if (cleanupRegistered) {
    return;
  }

  cleanupRegistered = true;
  process.once("exit", () => {
    for (const cacheDirectory of cacheDirectories) {
      try {
        rmSync(cacheDirectory, { force: true, recursive: true });
      } catch {
        // A cleanup failure must not replace the verification result.
      }
    }
  });
}

/** Keeps programmatic Vite servers away from a concurrently running dev server. */
export function createViteTestCacheDir() {
  const cacheDirectory = mkdtempSync(
    join(tmpdir(), "resumate-vite-test-cache-"),
  );
  cacheDirectories.add(cacheDirectory);
  registerCleanup();
  return cacheDirectory;
}
