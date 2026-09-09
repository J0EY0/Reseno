import assert from "node:assert/strict";
import test from "node:test";
import ts from "typescript";
import {
  collectImports,
  findJsxElements,
  getJsxAttributes,
  getLiteralValue,
  getMemberPath,
  hasCall,
  hasImport,
  parseSource,
} from "./source-analysis.mjs";

test("module boundaries use syntax instead of comments or quote style", () => {
  const source = parseSource(`
    import type { Payload } from '@/types/api'
    import { loadPreview } from '@/lib/preview'
    export { helper } from "./helper";
    const text = 'import("./unrelated")'
    // import("./comment")
    const load = () => import(
      "./document",
    )
  `);
  assert.deepEqual(
    collectImports(source).map(({ specifier }) => specifier),
    ["@/types/api", "@/lib/preview", "./helper", "./document"],
  );
  assert.equal(hasImport(source, "@/types/api"), false);
  assert.equal(hasImport(source, "./document"), false);
  assert.equal(hasImport(source, "./document", { dynamic: true }), true);
});

test("JSX capability checks accept reordered and reformatted attributes", () => {
  const renderings = [
    "<Editor updateContent={commands.updateContent} openSectionId={state.openSectionId} tabIndex={-1} />",
    `<Editor\n tabIndex={ -1 }\n openSectionId = { state.openSectionId }\n updateContent = { commands.updateContent }\n/>`,
  ];
  for (const rendering of renderings) {
    const [element] = findJsxElements(parseSource(rendering), "Editor");
    const attributes = getJsxAttributes(element);
    assert.equal(
      getMemberPath(attributes.get("updateContent")),
      "commands.updateContent",
    );
    assert.equal(
      getMemberPath(attributes.get("openSectionId")),
      "state.openSectionId",
    );
    assert.equal(getLiteralValue(attributes.get("tabIndex")), -1);
    assert.equal(attributes.has("key"), false);
  }
  assert.equal(
    hasCall(parseSource('const text = "preload()"'), "preload"),
    false,
  );
  assert.equal(hasCall(parseSource("void preload(\n)\n"), "preload"), true);
});

test("runtime boundaries match TypeScript verbatim module emission", () => {
  const source = `
    import type { Payload } from './payload'
    export type { Settings } from './settings'
    import { type Result } from './inline-payload'
    export { type Options } from './inline-options'
    import { type Config, read } from './mixed'
    import Default, { type Props } from './default'
    import './side-effect'
    export { type State, create } from './factory'
    export * from './all'
  `;
  const runtimeImports = (text) =>
    collectImports(parseSource(text))
      .filter((entry) => !entry.typeOnly)
      .map((entry) => entry.specifier);
  const emitted = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      verbatimModuleSyntax: true,
    },
  }).outputText;
  assert.deepEqual(runtimeImports(source), runtimeImports(emitted));
  assert.deepEqual(runtimeImports(source), [
    "./inline-payload",
    "./inline-options",
    "./mixed",
    "./default",
    "./side-effect",
    "./factory",
    "./all",
  ]);
});
