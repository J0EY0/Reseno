import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const sourceRoot = path.join(frontendRoot, "src");

const DEFAULT_FILE_LIMITS = Object.freeze({
  ".ts": 600,
  ".tsx": 500,
});
const DEFAULT_COMPONENT_BODY_LIMIT = 250;
const RATCHET_THRESHOLD_LINES = 10;

// These exact ceilings freeze existing debt. A ceiling may only stay flat or fall.
// Remove an entry once its source is within the default budget.
const LEGACY_FILE_CEILINGS = Object.freeze({});

// Keys are `<source path>#<component symbol>`, never directory patterns.
const LEGACY_COMPONENT_CEILINGS = Object.freeze({});

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
  const startLine = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line;
  const endLine = sourceFile.getLineAndCharacterOfPosition(node.getEnd()).line;
  return endLine - startLine + 1;
}

function collectReactComponents(sourceFile) {
  const components = [];
  const seenSymbols = new Set();

  function record(symbol, implementation) {
    if (
      (symbol !== "default" && !isPascalCase(symbol)) ||
      !containsJsx(implementation.body)
    ) {
      return;
    }

    if (seenSymbols.has(symbol)) {
      throw new Error(
        `${sourceFile.fileName} declares the React component symbol ${symbol} more than once.`,
      );
    }

    seenSymbols.add(symbol);
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
    } else if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
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

function validateExceptionKeys() {
  const errors = [];

  for (const sourcePath of Object.keys(LEGACY_FILE_CEILINGS)) {
    if (/[*?[\]]/.test(sourcePath) || !sourcePath.startsWith("src/")) {
      errors.push(`Invalid file exception key: ${sourcePath}`);
    }
  }

  for (const componentKey of Object.keys(LEGACY_COMPONENT_CEILINGS)) {
    if (
      /[*?[\]]/.test(componentKey) ||
      !/^src\/.+\.(?:ts|tsx)#(?:default|[A-Z][A-Za-z0-9]*)$/.test(
        componentKey,
      )
    ) {
      errors.push(`Invalid component exception key: ${componentKey}`);
    }
  }

  return errors;
}

function verifyBudget({ actual, ceiling, defaultLimit, key, kind }) {
  if (ceiling === undefined) {
    return actual > defaultLimit
      ? [`${key} has ${actual} ${kind}; default limit is ${defaultLimit}. Add an exact legacy ceiling or split it.`]
      : [];
  }

  if (!Number.isInteger(ceiling) || ceiling <= defaultLimit) {
    return [`${key} has an invalid legacy ceiling ${ceiling}; it must be an integer above ${defaultLimit}.`];
  }

  if (actual <= defaultLimit) {
    return [`${key} is within the default ${defaultLimit}-${kind} limit; remove its stale legacy ceiling.`];
  }

  if (actual > ceiling) {
    return [`${key} grew to ${actual} ${kind}; frozen legacy ceiling is ${ceiling}.`];
  }

  if (ceiling - actual >= RATCHET_THRESHOLD_LINES) {
    return [`${key} fell to ${actual} ${kind}; ratchet its legacy ceiling down from ${ceiling}.`];
  }

  return [];
}

const failures = validateExceptionKeys();
const seenFileExceptions = new Set();
const seenComponentExceptions = new Set();

for (const absolutePath of await collectSourceFiles(sourceRoot)) {
  const source = await readFile(absolutePath, "utf8");
  const sourcePath = path.relative(frontendRoot, absolutePath).split(path.sep).join("/");
  const extension = path.extname(absolutePath);
  const fileCeiling = LEGACY_FILE_CEILINGS[sourcePath];

  if (fileCeiling !== undefined) {
    seenFileExceptions.add(sourcePath);
  }

  failures.push(
    ...verifyBudget({
      actual: countLines(source),
      ceiling: fileCeiling,
      defaultLimit: DEFAULT_FILE_LIMITS[extension],
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
    const componentCeiling = LEGACY_COMPONENT_CEILINGS[componentKey];

    if (componentCeiling !== undefined) {
      seenComponentExceptions.add(componentKey);
    }

    failures.push(
      ...verifyBudget({
        actual: component.lines,
        ceiling: componentCeiling,
        defaultLimit: DEFAULT_COMPONENT_BODY_LIMIT,
        key: componentKey,
        kind: "line component body",
      }),
    );
  }
}

for (const sourcePath of Object.keys(LEGACY_FILE_CEILINGS)) {
  if (!seenFileExceptions.has(sourcePath)) {
    failures.push(`${sourcePath} has a stale legacy file ceiling: the source file does not exist.`);
  }
}

for (const componentKey of Object.keys(LEGACY_COMPONENT_CEILINGS)) {
  if (!seenComponentExceptions.has(componentKey)) {
    failures.push(`${componentKey} has a stale legacy component ceiling: the component was not found.`);
  }
}

if (failures.length > 0) {
  console.error("Source budget verification failed:\n");
  for (const failure of failures.sort()) {
    console.error(`- ${failure}`);
  }
  process.exitCode = 1;
} else {
  console.log("Source file and React component budgets verified.");
}
