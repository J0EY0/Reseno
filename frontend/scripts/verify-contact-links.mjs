import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import vm from "node:vm";
import * as ts from "typescript";

const root = new URL("..", import.meta.url).pathname;
const helperPath = join(root, "src", "lib", "contact-links.ts");
const source = await readFile(helperPath, "utf8");
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
  URL,
  Set,
});

const { createContactHref, normalizeContactFieldType } = module.exports;

assert.equal(normalizeContactFieldType("url"), "url");
assert.equal(normalizeContactFieldType("javascript"), "text");
assert.equal(createContactHref("text", "https://example.com"), null);
assert.equal(
  createContactHref("email", "name@example.com"),
  "mailto:name@example.com",
);
assert.equal(
  createContactHref("phone", "+86 13800000000"),
  "tel:+86 13800000000",
);
assert.equal(
  createContactHref("url", "github.com/example"),
  "https://github.com/example",
);
assert.equal(
  createContactHref("url", "http://example.com/profile"),
  "http://example.com/profile",
);
assert.equal(createContactHref("url", "javascript:alert(1)"), null);
assert.equal(createContactHref("url", "data:text/html,test"), null);
assert.equal(createContactHref("url", "ftp://example.com/file"), null);
assert.equal(createContactHref("email", "https://example.com"), null);
assert.equal(createContactHref("phone", "mailto:name@example.com"), null);
assert.equal(createContactHref("url", "https://"), null);
assert.equal(createContactHref("url", "https://example.com\nunsafe"), null);

console.log("Contact link verification passed.");
