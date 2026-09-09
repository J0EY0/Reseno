import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const sourceRoot = path.join(frontendRoot, "src");

const DEFAULT_FILE_THRESHOLDS = Object.freeze({
  ".ts": 600,
  ".tsx": 500,
});
const DEFAULT_COMPONENT_BODY_THRESHOLD = 250;

function countLines(source) {
  if (source.length === 0) {
    return 0;
  }

  const lines = source.split(/\r\n|\n|\r/).length;
  return /(?:\r\n|\n|\r)$/.test(source) ? lines - 1 : lines;
}

async function collectSourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const entryPath = path.join(directory, entry.name);

    if (entry.isDirectory()) {
      files.push(...(await collectSourceFiles(entryPath)));
    } else if (entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")) {
      files.push(entryPath);
    }
  }

  return files.sort();
}

function isPascalCase(name) {
  return /^[A-Z][A-Za-z0-9]*$/.test(name);
}

function isComponentWrapper(expression) {
  if (ts.isIdentifier(expression)) {
    return expression.text === "memo" || expression.text === "forwardRef";
  }

  return (
    ts.isPropertyAccessExpression(expression) &&
    (expression.name.text === "memo" || expression.name.text === "forwardRef")
  );
}

function unwrapComponentFunction(initializer) {
  let expression = initializer;

  while (
    ts.isParenthesizedExpression(expression) ||
    ts.isAsExpression(expression) ||
    ts.isSatisfiesExpression(expression) ||
    ts.isNonNullExpression(expression)
  ) {
    expression = expression.expression;
  }

  if (ts.isArrowFunction(expression) || ts.isFunctionExpression(expression)) {
    return expression;
  }

  if (
    ts.isCallExpression(expression) &&
    isComponentWrapper(expression.expression) &&
    expression.arguments.length > 0
  ) {
    return unwrapComponentFunction(expression.arguments[0]);
  }

  return null;
}

function containsJsx(node) {
  let found = false;

  function visit(current) {
    if (found) {
      return;
    }

    if (
      ts.isJsxElement(current) ||
      ts.isJsxSelfClosingElement(current) ||
      ts.isJsxFragment(current)
    ) {
      found = true;
      return;
    }

    ts.forEachChild(current, visit);
  }

  visit(node);
  return found;
}

function getNodeLineSpan(sourceFile, node) {
  const startLine = sourceFile.getLineAndCharacterOfPosition(
    node.getStart(sourceFile),
  ).line;
  const endLine = sourceFile.getLineAndCharacterOfPosition(node.getEnd()).line;
  return endLine - startLine + 1;
}

function collectReactComponents(sourceFile) {
  const components = [];

  function record(symbol, implementation) {
    if (
      (symbol !== "default" && !isPascalCase(symbol)) ||
      !containsJsx(implementation.body)
    ) {
      return;
    }

    components.push({
      symbol,
      lines: getNodeLineSpan(sourceFile, implementation.body),
    });
  }

  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.body) {
      const isDefaultExport = node.modifiers?.some(
        (modifier) => modifier.kind === ts.SyntaxKind.DefaultKeyword,
      );

      if (node.name || isDefaultExport) {
        record(node.name?.text ?? "default", node);
      }
    } else if (
      ts.isVariableDeclaration(node) &&
      ts.isIdentifier(node.name) &&
      node.initializer
    ) {
      const implementation = unwrapComponentFunction(node.initializer);

      if (implementation) {
        record(node.name.text, implementation);
      }
    } else if (ts.isExportAssignment(node)) {
      const implementation = unwrapComponentFunction(node.expression);

      if (implementation) {
        record(implementation.name?.text ?? "default", implementation);
      }
    }

    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return components;
}

function getSizeDiagnostics({ actual, threshold, key, kind }) {
  return actual > threshold
    ? [`${key} has ${actual} ${kind}; review threshold is ${threshold}.`]
    : [];
}

const diagnostics = [];

for (const absolutePath of await collectSourceFiles(sourceRoot)) {
  const source = await readFile(absolutePath, "utf8");
  const sourcePath = path
    .relative(frontendRoot, absolutePath)
    .split(path.sep)
    .join("/");
  const extension = path.extname(absolutePath);
  diagnostics.push(
    ...getSizeDiagnostics({
      actual: countLines(source),
      threshold: DEFAULT_FILE_THRESHOLDS[extension],
      key: sourcePath,
      kind: "line file",
    }),
  );

  if (extension !== ".tsx") {
    continue;
  }

  const sourceFile = ts.createSourceFile(
    absolutePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );

  for (const component of collectReactComponents(sourceFile)) {
    const componentKey = `${sourcePath}#${component.symbol}`;
    diagnostics.push(
      ...getSizeDiagnostics({
        actual: component.lines,
        threshold: DEFAULT_COMPONENT_BODY_THRESHOLD,
        key: componentKey,
        kind: "line component body",
      }),
    );
  }
}

if (diagnostics.length > 0) {
  console.log("Source size diagnostics:\n");
  for (const diagnostic of diagnostics.sort()) {
    console.log(`- ${diagnostic}`);
  }
} else {
  console.log(
    "Source file and React component sizes are within review thresholds.",
  );
}
