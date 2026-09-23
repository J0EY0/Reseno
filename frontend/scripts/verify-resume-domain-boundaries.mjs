import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import {
  hasCall,
  hasImport,
  hasObjectProperty,
  parseSource,
} from "./source-analysis.mjs";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const sourceRoot = path.join(frontendRoot, "src");
const domainModules = new Map([
  [
    "lib/template-presets.generated.ts",
    ["GeneratedBuiltinTemplateId", "builtinTemplatePresets"],
  ],
  [
    "lib/template-presets.ts",
    [
      "builtinTemplateIds",
      "getBuiltinTemplatePreset",
      "getBuiltinTemplateStarter",
      "isBuiltinTemplateId",
    ],
  ],
  [
    "lib/templates.ts",
    [
      "DEFAULT_TEMPLATE_IMAGE",
      "createCustomTemplateFromBase",
      "createTemplateImageElement",
      "createTemplateLayout",
      "createTemplateSettings",
      "getBuiltInTemplates",
      "getResumeFontSizeInPoints",
      "getTemplateById",
      "getTemplateCatalog",
      "resumeFontSizeOptions",
      "timelineSectionKinds",
    ],
  ],
  [
    "lib/resume-sections.ts",
    [
      "RenderableResumeSection",
      "RenderableSectionItem",
      "SECTION_ITEM_FIELDS",
      "SECTION_RENDER_FAMILY",
      "createResumeSection",
      "createSectionItem",
      "hasSectionContent",
      "hasSectionItemContent",
      "isCanonicalResumeSection",
      "isSectionItemForKind",
      "projectResumeSection",
      "projectResumeSections",
    ],
  ],
  [
    "lib/resume-section-mutations.ts",
    [
      "ResumeSectionMutation",
      "ResumeSectionMutationResult",
      "applySectionMutation",
    ],
  ],
]);

function hasExportModifier(node) {
  return node.modifiers?.some(
    (modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword,
  );
}

function collectExportedNames(sourceFile) {
  const names = new Set();

  for (const statement of sourceFile.statements) {
    assert.equal(
      ts.isExportDeclaration(statement),
      false,
      `${sourceFile.fileName} must not become a barrel or compatibility facade.`,
    );

    if (!hasExportModifier(statement)) {
      continue;
    }

    if (
      (ts.isFunctionDeclaration(statement) ||
        ts.isClassDeclaration(statement) ||
        ts.isInterfaceDeclaration(statement) ||
        ts.isTypeAliasDeclaration(statement) ||
        ts.isEnumDeclaration(statement)) &&
      statement.name
    ) {
      names.add(statement.name.text);
      continue;
    }

    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        assert(
          ts.isIdentifier(declaration.name),
          `${sourceFile.fileName} must use named domain exports.`,
        );
        names.add(declaration.name.text);
      }
    }
  }

  return [...names].sort();
}

function resolveDomainImport(modulePath, specifier) {
  let resolved;

  if (specifier.startsWith("@/")) {
    resolved = specifier.slice(2);
  } else if (specifier.startsWith(".")) {
    resolved = path.posix.normalize(
      path.posix.join(path.posix.dirname(modulePath), specifier),
    );
  } else {
    return null;
  }

  const withExtension = resolved.endsWith(".ts") ? resolved : `${resolved}.ts`;
  return domainModules.has(withExtension) ? withExtension : null;
}

function collectDomainDependencies(sourceFile, modulePath) {
  const dependencies = new Set();

  for (const statement of sourceFile.statements) {
    if (!ts.isImportDeclaration(statement)) {
      continue;
    }

    const specifier = statement.moduleSpecifier.text;
    const dependency = resolveDomainImport(modulePath, specifier);
    if (dependency) {
      dependencies.add(dependency);
    }
  }

  return dependencies;
}

function assertAcyclic(graph) {
  const visiting = new Set();
  const visited = new Set();

  function visit(modulePath, trail) {
    if (visiting.has(modulePath)) {
      throw new Error(
        `Resume domain modules must remain acyclic: ${[
          ...trail,
          modulePath,
        ].join(" -> ")}`,
      );
    }
    if (visited.has(modulePath)) {
      return;
    }

    visiting.add(modulePath);
    for (const dependency of graph.get(modulePath) ?? []) {
      visit(dependency, [...trail, modulePath]);
    }
    visiting.delete(modulePath);
    visited.add(modulePath);
  }

  for (const modulePath of graph.keys()) {
    visit(modulePath, []);
  }
}

const graph = new Map();
const productExports = new Set();

for (const [modulePath, expectedExports] of domainModules) {
  const absolutePath = path.join(sourceRoot, modulePath);
  const source = await readFile(absolutePath, "utf8");
  const sourceFile = ts.createSourceFile(
    modulePath,
    source,
    ts.ScriptTarget.Latest,
    true,
  );

  assert.deepEqual(
    collectExportedNames(sourceFile),
    [...expectedExports].sort(),
    `${modulePath} changed its deliberate domain interface.`,
  );

  graph.set(modulePath, collectDomainDependencies(sourceFile, modulePath));
  for (const exportedName of expectedExports) {
    if (exportedName !== "getBuiltinTemplatePreset") {
      assert.equal(
        productExports.has(exportedName),
        false,
        `${exportedName} must have a single owning module.`,
      );
      productExports.add(exportedName);
    }
  }
}

assertAcyclic(graph);
assert.deepEqual(
  [...graph.get("lib/templates.ts")],
  ["lib/template-presets.ts", "lib/resume-sections.ts"],
  "Template normalization must consume the preset registry and canonical section families one-way.",
);
assert.deepEqual(
  [...graph.get("lib/template-presets.ts")],
  ["lib/template-presets.generated.ts"],
  "The preset registry must depend only on its generated canonical data.",
);
assert.deepEqual(
  [...graph.get("lib/template-presets.generated.ts")],
  [],
  "Generated preset data must not depend on handwritten domain modules.",
);
assert.deepEqual(
  [...graph.get("lib/resume-section-mutations.ts")],
  ["lib/resume-sections.ts"],
  "Immutable mutations must consume the canonical section schema one-way.",
);
assert.deepEqual(
  [...graph.get("lib/resume-sections.ts")],
  [],
  "The canonical section schema must not depend on editor mutations.",
);

const [
  exportApi,
  editorPane,
  editorCard,
  sectionContent,
  sectionEditors,
  sectionEditorFields,
  ...typedSectionEditors
] = await Promise.all([
  readFile(path.join(sourceRoot, "lib/export-api.ts"), "utf8"),
  readFile(
    path.join(sourceRoot, "components/editor/resume-editor-pane.tsx"),
    "utf8",
  ),
  readFile(
    path.join(sourceRoot, "components/editor/resume-section-card.tsx"),
    "utf8",
  ),
  readFile(
    path.join(sourceRoot, "components/editor/resume-section-content.tsx"),
    "utf8",
  ),
  readFile(
    path.join(sourceRoot, "components/editor/resume-section-editors.tsx"),
    "utf8",
  ),
  readFile(
    path.join(sourceRoot, "components/editor/resume-section-editor-fields.tsx"),
    "utf8",
  ),
  ...[
    "education-section-editor.tsx",
    "experience-section-editor.tsx",
    "project-section-editor.tsx",
    "achievement-section-editor.tsx",
    "simple-list-section-editor.tsx",
  ].map((moduleName) =>
    readFile(path.join(sourceRoot, "components/editor", moduleName), "utf8"),
  ),
]);

assert(
  exportApi.includes('from "@/lib/template-presets"') &&
    !exportApi.includes('from "@/lib/templates"'),
  "Built-in template identity checks must import the preset registry directly.",
);
for (const source of [editorPane, editorCard, sectionContent, sectionEditors]) {
  assert(
    source.includes("@/lib/resume-section-mutations"),
    "Editor mutation callers must import the immutable mutation module directly.",
  );
}
assert.deepEqual(
  [
    "education-section-editor",
    "experience-section-editor",
    "project-section-editor",
    "achievement-section-editor",
    "simple-list-section-editor",
  ].filter((moduleName) => sectionEditors.includes(`./${moduleName}`)),
  [
    "education-section-editor",
    "experience-section-editor",
    "project-section-editor",
    "achievement-section-editor",
    "simple-list-section-editor",
  ],
  "The section dispatcher must import each typed editor through its narrow module.",
);
const sectionFile = parseSource(sectionEditors);
assert(
  hasCall(sectionFile, "toast.info") &&
    hasObjectProperty(sectionFile, "type", "item.restore") &&
    hasObjectProperty(sectionFile, "type", "item.remove"),
  "Section deletion must retain its snapshot-based undo mutation.",
);
assert(
  hasImport(parseSource(sectionEditorFields), "./rich-highlights-editor", {
    dynamic: true,
  }),
  "Shared section fields must retain the rich-editor lazy boundary.",
);
for (const [index, sectionKind] of [
  "education",
  "experience",
  "project",
  "achievement",
  "simple_list",
].entries()) {
  assert(
    hasObjectProperty(
      parseSource(typedSectionEditors[index]),
      "sectionKind",
      sectionKind,
    ),
    `The ${sectionKind} editor must publish its own discriminated update mutation.`,
  );
}

console.log(
  "Resume template/section module interfaces and dependencies verified.",
);
