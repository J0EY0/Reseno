import { readFile } from "node:fs/promises";
import vm from "node:vm";
import ts from "typescript";

export function evaluateTypeScript(
  source,
  {
    filename = "module.ts",
    globals = {},
    imports = {},
    resolveImport,
    context = vm.createContext({ ...globals }),
  } = {},
) {
  const compiled = ts.transpileModule(source, {
    fileName: String(filename),
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  const module = { exports: {} };
  const require = (specifier) => {
    if (Object.hasOwn(imports, specifier)) {
      return imports[specifier];
    }
    const resolved = resolveImport?.(specifier);
    if (resolved !== undefined) {
      return resolved;
    }
    throw new Error(`Unexpected import ${specifier} in ${filename}`);
  };
  const execute = new vm.Script(
    `(function (module, exports, require) {\n${compiled}\n})`,
    { filename: String(filename) },
  ).runInContext(context);
  execute(module, module.exports, require);
  return module.exports;
}

export async function loadTypeScriptModule(filename, options = {}) {
  const source = await readFile(filename, "utf8");
  return evaluateTypeScript(source, { ...options, filename });
}
