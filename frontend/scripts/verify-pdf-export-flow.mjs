import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import * as ts from "typescript";

const frontendRoot = new URL("../", import.meta.url);

async function readText(path) {
  return readFile(new URL(path, frontendRoot), "utf8");
}

const [builderSource, rendererSource, exportApiSource, appSource, zhSource, enSource] =
  await Promise.all([
    readText("src/components/resume-builder.tsx"),
    readText("src/components/pdf-export-renderer.tsx"),
    readText("src/lib/export-api.ts"),
    readText("src/App.tsx"),
    readText("src/i18n/locales/zh.json"),
    readText("src/i18n/locales/en.json"),
  ]);

const builderFile = ts.createSourceFile(
  "resume-builder.tsx",
  builderSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);

function findFunctionDeclaration(name) {
  let match;

  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === name) {
      match = node;
      return;
    }

    ts.forEachChild(node, visit);
  }

  visit(builderFile);
  return match;
}

function findCalls(root, name) {
  const calls = [];

  function visit(node) {
    if (
      ts.isCallExpression(node) &&
      ((ts.isIdentifier(node.expression) && node.expression.text === name) ||
        (ts.isPropertyAccessExpression(node.expression) &&
          node.expression.getText(builderFile) === name))
    ) {
      calls.push(node);
    }

    ts.forEachChild(node, visit);
  }

  visit(root);
  return calls;
}

const exportPdf = findFunctionDeclaration("exportPdf");
assert.ok(exportPdf, "ResumeBuilder must define its PDF export action.");

const exportPdfSource = exportPdf.getText(builderFile);
const saveCalls = findCalls(exportPdf, "saveCurrentWorkspace");
const requestCalls = findCalls(exportPdf, "requestResumePdfExport");
const downloadCalls = findCalls(exportPdf, "downloadExportedPdf");
const successToastCalls = findCalls(exportPdf, "toast.success");
const errorToastCalls = findCalls(exportPdf, "toast.error");

assert.equal(
  saveCalls.length,
  1,
  "PDF export must persist the current resume before requesting an artifact.",
);
assert.ok(
  saveCalls[0].parent && ts.isAwaitExpression(saveCalls[0].parent),
  "PDF export must wait for the current resume save to finish.",
);
assert.equal(
  requestCalls.length,
  1,
  "PDF export must request one server-generated PDF artifact.",
);
assert.equal(
  downloadCalls.length,
  1,
  "PDF export must download the generated PDF artifact.",
);
assert.ok(
  requestCalls[0].parent && ts.isAwaitExpression(requestCalls[0].parent),
  "PDF generation must finish before starting the download.",
);
assert.ok(
  downloadCalls[0].parent && ts.isAwaitExpression(downloadCalls[0].parent),
  "PDF download must finish before reporting success.",
);
assert.ok(
  saveCalls[0].getStart(builderFile) < requestCalls[0].getStart(builderFile) &&
    requestCalls[0].getStart(builderFile) < downloadCalls[0].getStart(builderFile),
  "PDF save, generation, and download must run in order.",
);
assert.equal(
  successToastCalls.length,
  1,
  "The PDF action must report one successful download.",
);
assert.ok(
  downloadCalls[0].getStart(builderFile) <
    successToastCalls[0].getStart(builderFile),
  "PDF export must report success only after the download completes.",
);

const requestArgument = requestCalls[0].arguments[0];
assert.ok(
  requestArgument && ts.isObjectLiteralExpression(requestArgument),
  "PDF generation must receive the saved resume export contract.",
);
const requestFields = new Map(
  requestArgument.properties.flatMap((property) => {
    if (ts.isShorthandPropertyAssignment(property)) {
      return [[property.name.text, property.name.text]];
    }
    if (ts.isPropertyAssignment(property)) {
      return [[property.name.getText(builderFile), property.initializer.getText(builderFile)]];
    }
    return [];
  }),
);

assert.equal(requestFields.get("resumeId"), "activeResume.id");
assert.equal(requestFields.get("locale"), "locale");
assert.equal(requestFields.get("fileNameSeed"), "activeResume.title");
assert.equal(requestFields.get("savedAt"), "savedVersion.savedAt");
assert.equal(requestFields.get("versionId"), "savedVersion.versionId");

const saveWorkspaceStart = builderSource.indexOf(
  "  const saveCurrentWorkspace = useCallback(",
);
const saveWorkspaceEnd = builderSource.indexOf(
  "\n  useEffect(() => {",
  saveWorkspaceStart,
);
assert.notEqual(saveWorkspaceStart, -1, "Workspace save action was not found.");
assert.notEqual(saveWorkspaceEnd, -1, "Workspace save action boundary was not found.");
const saveWorkspaceSource = builderSource.slice(
  saveWorkspaceStart,
  saveWorkspaceEnd,
);
assert.match(
  saveWorkspaceSource,
  /while \(saveRequestRef\.current\) \{[\s\S]*?await activeRequest\.promise[\s\S]*?activeRequest\.targetKey === saveTargetKey[\s\S]*?latestCompletedSave = completedSave/,
  "A new save or export must wait for an active save and reuse its matching version.",
);

assert.doesNotMatch(
  builderSource,
  /createPdfExportFrame|buildPdfExportUrl|createElement\(["']iframe["']\)/,
  "The editor must not create a hidden iframe for PDF export.",
);
assert.doesNotMatch(
  builderSource,
  /window\.print\s*\(/,
  "The editor must not invoke the browser print dialog.",
);
assert.doesNotMatch(
  rendererSource,
  /window\.print\s*\(|searchParams\.get\(["']print["']\)|\bshouldPrint\b|\bhasPrintedRef\b/,
  "The internal renderer must not invoke or prepare the browser print dialog.",
);

assert.equal(
  errorToastCalls.length,
  1,
  "The PDF action must have only one local fallback error Toast.",
);
assert.match(
  exportPdfSource,
  /if\s*\(\s*!isApiErrorToastShown\(error\)\s*\)\s*\{[\s\S]*?toast\.error\(/,
  "The PDF action must not duplicate an error Toast already shown by the API client.",
);

assert.match(
  exportApiSource,
  /requestResumePdfExport[\s\S]*?requestApi<ExportResumePdfResponse>\(apiRoutes\.resumePdfExport/,
  "PDF generation must use the authenticated export endpoint helper.",
);
assert.match(
  exportApiSource,
  /downloadExportedPdf[\s\S]*?downloadExportedFile\(result\)/,
  "PDF download must reuse the authenticated Blob download helper.",
);
assert.match(
  exportApiSource,
  /fetchApiResource\(result\.downloadUrl\)[\s\S]*?response\.blob\(\)[\s\S]*?downloadBlob\(blob, result\.fileName\)/,
  "PDF download must use the server filename for the downloaded Blob.",
);

assert.match(
  rendererSource,
  /waitForRenderAssets\(\)[\s\S]*?data-pdf-ready=\{isReady \? ["']true["'] : ["']false["']\}/,
  "The internal renderer must keep the Playwright readiness handshake.",
);
assert.equal(
  appSource.match(/path=["']\/pdf-export["']/g)?.length,
  2,
  "The internal PDF render route must remain available in both auth route trees.",
);

const zh = JSON.parse(zhSource);
const en = JSON.parse(enSource);
assert.doesNotMatch(
  zh.exportSuccess,
  /打开浏览器|打印|预览/,
  "Chinese success copy must describe a completed download, not native print UI.",
);
assert.doesNotMatch(
  en.exportSuccess,
  /open(?:ing)? browser|print|preview/i,
  "English success copy must describe a completed download, not native print UI.",
);

console.log("Direct PDF export flow verified.");
