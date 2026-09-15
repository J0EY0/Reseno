import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SettingsPanel } from "@/components/settings-panel";
import type { SettingsPanelProps } from "@/components/settings-panel-types";
import { defaultMessages as t } from "@/i18n";
import { clearApiCache } from "@/lib/api-client";
import { saveAuthSession } from "@/lib/auth-session";
import { createDefaultModelConfig } from "@/lib/model-config";
import { deferred } from "./helpers/pdf-browser-fixtures";
import { jsonResponse } from "./helpers/pdf-import-fixtures";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restoreBrowserApis: () => void;
const passwordReplies: Promise<Response>[] = [];
let passwordRequests: RequestInit[];
let sessionNumber = 0;
beforeEach(() => {
  restoreBrowserApis = installPanelBrowserApis();
  clearApiCache();
  localStorage.clear();
  saveAuthSession(
    "owner",
    `settings-token-${++sessionNumber}`,
    "2999-01-01T00:00:00Z",
  );
  passwordRequests = [];
  passwordReplies.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = new URL(String(input), location.href).pathname;
      if (path === "/api/auth/oauth/identities")
        return jsonResponse({ identities: [], providers: [] });
      if (path === "/api/auth/password") {
        passwordRequests.push(init);
        const reply = passwordReplies.shift();
        expect(reply).toBeDefined();
        return reply!;
      }
      throw new Error(`Unexpected settings request: ${path}`);
    }),
  );
});
afterEach(() => {
  cleanup();
  restoreBrowserApis();
  vi.unstubAllGlobals();
  localStorage.clear();
  expect(passwordReplies).toEqual([]);
});

function renderSettings(url = "/settings?keep=1") {
  const props: SettingsPanelProps = {
    locale: "en",
    t,
    theme: "light",
    onThemeChange: vi.fn(),
    onLocaleChange: vi.fn(),
    onPasswordChanged: vi.fn(),
    agentSettings: {
      defaultModelConfigId: "model-a",
      responseLanguage: "follow",
      behaviorMode: "balanced",
      confirmationMode: "always",
    },
    onAgentSettingsChange: vi.fn(),
    modelConfigs: [
      createDefaultModelConfig("en", {
        id: "model-a",
        nickname: "Model A",
        supportsTools: true,
      }),
      createDefaultModelConfig("en", {
        id: "model-b",
        nickname: "Model B",
        supportsTools: true,
      }),
    ],
  };
  const router = createMemoryRouter(
    [{ path: "*", element: <SettingsPanel {...props} /> }],
    { initialEntries: [url] },
  );
  const view = render(<RouterProvider router={router} />);
  return { ...view, props, router };
}
async function select(label: string, option: string) {
  fireEvent.keyDown(screen.getByRole("combobox", { name: label }), {
    key: "ArrowDown",
  });
  const list = screen.getByRole("listbox");
  expect(list.getAttribute("data-align")).toBe("end");
  await waitFor(() =>
    expect(list.parentElement?.style.transform).toBe("translate(0px, 4px)"),
  );
  expect(list.className).toContain("w-[var(--radix-select-trigger-width)]");
  expect(list.className).not.toContain("min-w-[20rem]");
  fireEvent.click(screen.getByRole("option", { name: option }));
  await act(async () => {});
}

it("keeps site preferences and account security grouped while wiring language, theme, and account dialogs", async () => {
  const { props, container } = renderSettings();
  await act(async () => {});
  const headings = screen.getAllByRole("heading", { level: 2 });
  expect(headings.map((node) => node.textContent)).toEqual([
    t.preferencesSettingsTitle,
    t.accountSecuritySettingsTitle,
  ]);
  for (const heading of headings) {
    expect(heading.querySelector("svg")).toBeNull();
    expect(heading.parentElement?.tagName).toBe("SECTION");
    expect(heading.closest('[data-slot="card"]')).toBeNull();
    expect(heading.nextElementSibling?.getAttribute("data-slot")).toBe("card");
  }
  const preferences = headings[0].parentElement!;
  expect(within(preferences).getAllByRole("group")).toHaveLength(2);
  expect(preferences.querySelectorAll('[data-slot="separator"]')).toHaveLength(
    1,
  );
  for (const label of [
    t.language,
    t.theme,
    t.usernameSettingsTitle,
    t.passwordSettingsTitle,
  ]) {
    const row = screen.getByRole("group", { name: label });
    for (const token of ["min-h-20", "py-4", "lg:min-h-16", "lg:py-3"])
      expect(row.classList.contains(token)).toBe(true);
  }
  const language = screen.getByRole("combobox", { name: t.language });
  for (const token of ["ml-auto", "w-28", "max-w-full"])
    expect(language.classList.contains(token)).toBe(true);
  await select(t.language, t.uiLanguageChinese);
  expect(props.onLocaleChange).toHaveBeenCalledExactlyOnceWith("zh");
  await select(t.theme, t.dark);
  expect(props.onThemeChange).toHaveBeenCalledExactlyOnceWith("dark");
  fireEvent.click(screen.getByRole("button", { name: t.updateUsername }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: t.cancel }),
  );
  fireEvent.click(screen.getByRole("button", { name: t.updatePassword }));
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(container.querySelector('[data-slot="card-header"]')).toBeNull();
});

it("keeps the active tab in the URL and emits each complete Agent settings change", async () => {
  const { router, props } = renderSettings("/settings?tab=agent&keep=1");
  await act(async () => {});
  expect(
    screen
      .getByRole("tab", { name: t.agentSettingsTitle })
      .getAttribute("aria-selected"),
  ).toBe("true");
  expect(
    screen
      .getAllByRole("heading", { level: 2 })
      .map((node) => node.textContent),
  ).toEqual([t.agentModelSettingsTitle, t.agentInteractionSettingsTitle]);
  const defaultModel = screen.getByRole("combobox", {
    name: t.defaultAgentModel,
  });
  for (const token of ["ml-auto", "w-full", "sm:max-w-64"])
    expect(defaultModel.classList.contains(token)).toBe(true);
  const response = screen.getByRole("combobox", {
    name: t.agentResponseLanguage,
  });
  for (const token of ["ml-auto", "w-auto", "min-w-44", "max-w-full"])
    expect(response.classList.contains(token)).toBe(true);
  for (const [label, option, patch] of [
    [t.defaultAgentModel, "Model B", { defaultModelConfigId: "model-b" }],
    [t.agentResponseLanguage, t.languageEnglish, { responseLanguage: "en" }],
    [t.agentBehavior, t.agentBehaviorStrict, { behaviorMode: "strict" }],
    [
      t.agentConfirmationMode,
      t.agentConfirmationSuggestOnly,
      { confirmationMode: "suggestOnly" },
    ],
  ] as const) {
    await select(label, option);
    expect(props.onAgentSettingsChange).toHaveBeenLastCalledWith({
      ...props.agentSettings,
      ...patch,
    });
  }
  expect(props.onAgentSettingsChange).toHaveBeenCalledTimes(4);
  fireEvent.mouseDown(screen.getByRole("tab", { name: t.siteSettingsTitle }), {
    button: 0,
  });
  expect(router.state.location.search).toBe("?keep=1");
  fireEvent.mouseDown(screen.getByRole("tab", { name: t.agentSettingsTitle }), {
    button: 0,
  });
  expect(router.state.location.search).toBe("?keep=1&tab=agent");
});

it("validates password fields before IO and preserves a failed form until the authenticated update succeeds", async () => {
  const { props } = renderSettings();
  await act(async () => {});
  fireEvent.click(screen.getByRole("button", { name: t.updatePassword }));
  const dialog = screen.getByRole("dialog");
  const form = dialog.querySelector("form")!;
  fireEvent.submit(form);
  expect(passwordRequests).toEqual([]);
  expect(
    dialog.querySelectorAll('[aria-invalid="true"]').length,
  ).toBeGreaterThan(0);
  fireEvent.change(
    within(dialog).getByLabelText(t.currentPassword, { exact: true }),
    { target: { value: "Old-password-1" } },
  );
  fireEvent.change(
    within(dialog).getByLabelText(t.newPassword, { exact: true }),
    { target: { value: "New-password-2" } },
  );
  fireEvent.change(
    within(dialog).getByLabelText(t.confirmPassword, { exact: true }),
    { target: { value: "New-password-2" } },
  );
  const first = deferred<Response>();
  passwordReplies.push(first.promise);
  fireEvent.submit(form);
  expect(
    form.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled,
  ).toBe(true);
  expect(form.querySelector('button[type="submit"]')?.textContent).toContain(
    t.passwordUpdating,
  );
  expect(props.onPasswordChanged).not.toHaveBeenCalled();
  await act(async () => first.reject(new Error("Password update failed")));
  expect(screen.getByRole("dialog")).toBe(dialog);
  expect(
    (
      within(dialog).getByLabelText(t.currentPassword, {
        exact: true,
      }) as HTMLInputElement
    ).value,
  ).toBe("Old-password-1");
  expect(dialog.querySelector(".text-destructive")).not.toBeNull();
  const second = deferred<Response>();
  passwordReplies.push(second.promise);
  fireEvent.submit(form);
  expect(passwordRequests).toHaveLength(2);
  expect(passwordRequests[1].method).toBe("POST");
  expect(JSON.parse(String(passwordRequests[1].body))).toEqual({
    currentPassword: "Old-password-1",
    newPassword: "New-password-2",
    confirmPassword: "New-password-2",
  });
  await act(async () =>
    second.resolve(jsonResponse({ username: "owner", updated: true })),
  );
  expect(props.onPasswordChanged).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog")).toBeNull();
});
