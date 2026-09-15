import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

function parseSource(path) {
  return ts.createSourceFile(
    path,
    readFileSync(new URL(`../${path}`, import.meta.url), "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
}
function descendants(root, predicate) {
  const found = [];
  function visit(node) {
    if (predicate(node)) found.push(node);
    ts.forEachChild(node, visit);
  }
  visit(root);
  return found;
}
const exportFile = parseSource(
  "src/components/workspace/use-resume-detail-export.ts",
);
const importsExportApi = (node) =>
  ts.isStringLiteral(node) && node.text === "@/lib/export-api";
assert.equal(
  descendants(
    exportFile,
    (node) =>
      ts.isImportDeclaration(node) && importsExportApi(node.moduleSpecifier),
  ).length,
  0,
  "PDF export API must remain outside the eager editor dependency graph.",
);
assert.equal(
  descendants(
    exportFile,
    (node) =>
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      importsExportApi(node.arguments[0]),
  ).length,
  1,
  "Export actions must share one optional API entry.",
);
const app = parseSource("src/App.tsx");
assert.equal(
  descendants(
    app,
    (node) =>
      (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) &&
      node.tagName.getText(app) === "Route" &&
      node.attributes.properties.some(
        (attribute) =>
          ts.isJsxAttribute(attribute) &&
          attribute.name.getText(app) === "path" &&
          attribute.initializer &&
          ts.isStringLiteral(attribute.initializer) &&
          attribute.initializer.text === "/pdf-export",
      ),
  ).length,
  2,
  "Both authentication route trees must expose the internal PDF render route.",
);
console.log("PDF export dependency and route boundaries verified.");
