import { readFile } from "node:fs/promises";
import ts from "typescript";

export function parseSource(source, filename = "module.tsx") {
  return ts.createSourceFile(
    filename,
    source,
    ts.ScriptTarget.Latest,
    true,
    filename.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
}

export async function readSourceFile(filename) {
  return parseSource(await readFile(filename, "utf8"), String(filename));
}

export function findNodes(root, predicate) {
  const nodes = [];
  function visit(node) {
    if (predicate(node)) nodes.push(node);
    ts.forEachChild(node, visit);
  }
  visit(root);
  return nodes;
}

export function getMemberPath(node) {
  if (!node) return undefined;
  if (ts.isIdentifier(node)) return node.text;
  if (ts.isPropertyAccessExpression(node)) {
    const owner = getMemberPath(node.expression);
    return owner ? `${owner}.${node.name.text}` : undefined;
  }
  return undefined;
}

export function collectImports(sourceFile) {
  return findNodes(
    sourceFile,
    (node) =>
      ts.isImportDeclaration(node) ||
      ts.isExportDeclaration(node) ||
      (ts.isCallExpression(node) &&
        node.expression.kind === ts.SyntaxKind.ImportKeyword),
  ).flatMap((node) => {
    const dynamic = ts.isCallExpression(node);
    const specifier = dynamic ? node.arguments[0] : node.moduleSpecifier;
    if (!specifier || !ts.isStringLiteral(specifier)) return [];
    return [
      {
        specifier: specifier.text,
        dynamic,
        typeOnly:
          !dynamic &&
          (node.isTypeOnly || node.importClause?.isTypeOnly || false),
      },
    ];
  });
}

export function hasImport(sourceFile, specifier, { dynamic = false } = {}) {
  return collectImports(sourceFile).some(
    (entry) =>
      entry.specifier === specifier &&
      entry.dynamic === dynamic &&
      !entry.typeOnly,
  );
}

export function findJsxElements(sourceFile, name) {
  return findNodes(
    sourceFile,
    (node) =>
      (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) &&
      getMemberPath(node.tagName) === name,
  );
}

export function getJsxAttributes(element) {
  return new Map(
    element.attributes.properties.flatMap((property) => {
      if (!ts.isJsxAttribute(property)) return [];
      const initializer = property.initializer;
      const value =
        initializer && ts.isJsxExpression(initializer)
          ? initializer.expression
          : initializer;
      return [[property.name.text, value]];
    }),
  );
}

export function getLiteralValue(node) {
  if (!node) return true;
  if (node.kind === ts.SyntaxKind.NullKeyword) return null;
  if (ts.isStringLiteralLike(node)) return node.text;
  if (ts.isNumericLiteral(node)) return Number(node.text);
  if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
  if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
  if (
    ts.isPrefixUnaryExpression(node) &&
    node.operator === ts.SyntaxKind.MinusToken
  ) {
    const value = getLiteralValue(node.operand);
    return typeof value === "number" ? -value : undefined;
  }
  return undefined;
}

export function hasCall(sourceFile, callee) {
  return (
    findNodes(
      sourceFile,
      (node) =>
        ts.isCallExpression(node) && getMemberPath(node.expression) === callee,
    ).length > 0
  );
}

export function findCalls(sourceFile, callee) {
  return findNodes(
    sourceFile,
    (node) =>
      ts.isCallExpression(node) && getMemberPath(node.expression) === callee,
  );
}

export function hasObjectProperty(sourceFile, name, value) {
  return findNodes(sourceFile, (node) => ts.isPropertyAssignment(node)).some(
    (property) =>
      (getMemberPath(property.name) ?? getLiteralValue(property.name)) ===
        name && getLiteralValue(property.initializer) === value,
  );
}
