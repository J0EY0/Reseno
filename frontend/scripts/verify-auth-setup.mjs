import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const authSession = await readFile(
  new URL("../src/lib/auth-session.ts", import.meta.url),
  "utf8",
);
assert.doesNotMatch(authSession, /import\.meta\.env\.PROD/);
console.log("Authentication session environment parity verified.");
