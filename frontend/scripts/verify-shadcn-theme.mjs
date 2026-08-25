import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const projectRoot = new URL("../", import.meta.url);
const [packageSource, themeSource, selectSource, appToasterSource] =
  await Promise.all([
    readFile(new URL("package.json", projectRoot), "utf8"),
    readFile(new URL("src/index.css", projectRoot), "utf8"),
    readFile(new URL("src/components/ui/select.tsx", projectRoot), "utf8"),
    readFile(new URL("src/components/app-toaster.tsx", projectRoot), "utf8"),
  ]);
const packageJson = JSON.parse(packageSource);

assert(
  packageJson.devDependencies?.["tw-animate-css"],
  "The shadcn animation styles must remain installed.",
);
assert(
  themeSource.includes('@import "tw-animate-css";'),
  "The global stylesheet must load the shadcn animation styles.",
);
assert(
  themeSource.includes("--color-input: var(--input);") &&
    (themeSource.match(/^\s*--input:/gm) ?? []).length === 2,
  "The input token must be mapped and defined for light and dark themes.",
);
for (const radiusToken of [
  "--radius-sm: calc(var(--radius) * 0.6);",
  "--radius-md: calc(var(--radius) * 0.8);",
  "--radius-lg: var(--radius);",
  "--radius-xl: calc(var(--radius) * 1.4);",
]) {
  assert(
    themeSource.includes(radiusToken),
    `The shadcn radius scale is missing ${radiusToken}`,
  );
}
assert(
  selectSource.includes("border-input") &&
    selectSource.includes("dark:bg-input/30") &&
    selectSource.includes("data-[state=open]:animate-in"),
  "Select must retain the shadcn input and popover style contract.",
);
const selectContentPopperClassName =
  selectSource.match(
    /<SelectPrimitive\.Content[\s\S]*?position === "popper"\s*&&\s*"([^"]*)"[\s\S]*?position=\{position\}/,
  )?.[1] ?? "";
const selectContentPopperClasses = new Set(
  selectContentPopperClassName.split(/\s+/),
);
assert(
  selectContentPopperClasses.has(
    "w-[var(--radix-select-trigger-width)]",
  ) &&
    selectContentPopperClasses.has(
      "min-w-[var(--radix-select-trigger-width)]",
    ),
  "Popper Select content must exactly match its trigger width.",
);

const toastStyleSource =
  appToasterSource.match(
    /style:\s*\{([\s\S]*?)\}\s*as CSSProperties/,
  )?.[1] ?? "";
let lastErrorVariableIndex = -1;
for (const errorVariable of [
  "--error-bg",
  "--error-border",
  "--error-text",
]) {
  const match = toastStyleSource.match(
    new RegExp(`"${errorVariable}"\\s*:\\s*"([^"]+)"`),
  );
  assert(
    match?.[1].includes("var(--destructive)"),
    `AppToaster ${errorVariable} must use the app destructive token.`,
  );
  lastErrorVariableIndex = Math.max(
    lastErrorVariableIndex,
    match.index ?? -1,
  );
}
assert(
  appToasterSource.includes("richColors") &&
    toastStyleSource.indexOf("...toastOptions?.style") >
      lastErrorVariableIndex &&
    appToasterSource.includes("...toastOptions,") &&
    appToasterSource.includes("...toastOptions?.classNames,"),
  "AppToaster must merge semantic error colors without discarding caller toast options.",
);

console.log("shadcn theme contract verified.");
