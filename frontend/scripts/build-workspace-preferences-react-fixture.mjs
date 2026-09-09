import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "vite";

const frontendRoot = fileURLToPath(new URL("../", import.meta.url));
const entry = path.join(
  frontendRoot,
  "workspace-preferences-react-fixture.jsx",
);
const api = "virtual:workspace-preferences-api";
const fixture = `
import React, { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { WorkspacePreferencesProvider } from "@/components/workspace/workspace-preferences";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import { useLocaleMessages } from "@/i18n/use-locale-messages";

const writes = [];
const pending = [];
let mode = "reject";
let preferences;
let mounted = true;
let currentLocale;
let setMounted;
let changeAppLocale;

window.savePreferences = (locale, settings) => {
  writes.push({ locale, settings });
  const response = { locale, ...settings };
  if (mode === "reject") return Promise.reject(new Error("Save failed"));
  if (mode === "success") return Promise.resolve(response);
  return new Promise((resolve, reject) => {
    pending.push({ resolve: () => resolve(response), reject });
  });
};

window.preferencesTest = {
  read: () => ({
    mounted,
    locale: currentLocale,
    preferences: preferences?.persistence.getSnapshot(),
    pending: pending.length,
    writes,
  }),
  mode: (next) => { mode = next; },
  settle: (success) => {
    const request = pending.shift();
    if (!request) throw new Error("No pending preference request");
    if (success) request.resolve();
    else request.reject(new Error("Save failed"));
  },
  restoreLocale: (locale) => changeAppLocale(locale),
  unmount: () => {
    mounted = false;
    setMounted(false);
    return changeAppLocale("zh");
  },
  flush: () => preferences.persistence.flush(),
};

function Probe() {
  preferences = useWorkspacePreferences();
  return <>
    <output id="workspace-locale">{preferences.locale}</output>
    <button onClick={() => preferences.changeLocale("en")}>English</button>
    <button onClick={() => preferences.changeLocale("zh")}>中文</button>
    <button onClick={() => preferences.changeTheme("dark")}>Dark</button>
  </>;
}

function App() {
  const [showWorkspace, setShowWorkspace] = useState(true);
  const { locale, messages, changeLocale, isMessagesReady } = useLocaleMessages("zh");
  currentLocale = locale;
  setMounted = setShowWorkspace;
  changeAppLocale = changeLocale;
  if (!showWorkspace) return <output id="outside-locale">{locale}</output>;
  if (!isMessagesReady) return null;
  return <WorkspacePreferencesProvider
    locale={locale}
    messages={messages}
    onLocaleChange={changeLocale}
  />;
}

const router = createMemoryRouter([
  { path: "/", element: <App />, children: [{ index: true, element: <Probe /> }] },
]);
createRoot(document.getElementById("root")).render(
  <StrictMode><RouterProvider router={router} /></StrictMode>,
);
`;

const result = await build({
  configFile: false,
  root: frontendRoot,
  logLevel: "silent",
  define: { "process.env.NODE_ENV": JSON.stringify("development") },
  resolve: {
    alias: [
      { find: "@/lib/workspace-api", replacement: api },
      { find: "@", replacement: path.join(frontendRoot, "src") },
    ],
  },
  plugins: [
    {
      name: "workspace-preferences-react-fixture",
      resolveId(id) {
        if (id === entry || id === api) return `\0${id}`;
      },
      load(id) {
        if (id === `\0${entry}`) return { code: fixture, moduleType: "jsx" };
        if (id === `\0${api}`) {
          return "export const saveUserSettingsApi = (...args) => window.savePreferences(...args);";
        }
      },
    },
  ],
  build: {
    write: false,
    minify: false,
    lib: { entry, name: "WorkspacePreferencesReactFixture", formats: ["iife"] },
  },
});
const output = Array.isArray(result) ? result[0].output : result.output;
process.stdout.write(output.find((item) => item.type === "chunk").code);
