import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

const parserModuleDirectory = new URL(
  "../src/lib/pdf-resume-import/",
  import.meta.url,
);
verifyAcyclicParserModules(parserModuleDirectory);
console.log("PDF parser dependency graph verified.");

function verifyAcyclicParserModules(directory) {
  const moduleNames = readdirSync(directory)
    .filter((name) => name.endsWith(".ts"))
    .sort();
  const graph = new Map(
    moduleNames.map((name) => {
      const source = readFileSync(new URL(name, directory), "utf8");
      const dependencies = Array.from(
        source.matchAll(/from\s+["']\.\/([^"']+)["']/g),
        (match) => `${match[1]}.ts`,
      ).filter((dependency) => moduleNames.includes(dependency));
      return [name, dependencies];
    }),
  );
  const visiting = new Set();
  const visited = new Set();

  function visit(moduleName, trail) {
    assert.ok(
      !visiting.has(moduleName),
      `PDF parser modules must stay acyclic: ${[...trail, moduleName].join(
        " -> ",
      )}`,
    );
    if (visited.has(moduleName)) {
      return;
    }

    visiting.add(moduleName);
    for (const dependency of graph.get(moduleName) ?? []) {
      visit(dependency, [...trail, moduleName]);
    }
    visiting.delete(moduleName);
    visited.add(moduleName);
  }

  for (const moduleName of moduleNames) {
    visit(moduleName, []);
  }
}
