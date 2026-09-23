import { act, fireEvent, render, screen } from "@testing-library/react";
import { lazy, Suspense, useState } from "react";
import { ErrorBoundary } from "react-error-boundary";
import { afterEach, expect, it, vi } from "vitest";

import { ResourceErrorBoundary } from "@/components/resource-error-boundary";
import { ResourceRecoveryContext } from "@/components/resource-recovery-context";
import { getTemplateEditorMessages } from "@/components/templates/editor/editor-messages";
import { TemplateEditorTabs } from "@/components/templates/template-editor-tabs";
import en from "@/i18n/locales/en.json";
import { getBuiltInTemplates } from "@/lib/templates";

vi.mock("@/components/templates/editor/visual-tab", () => ({
  TemplateVisualTab: () => {
    throw new TypeError(
      "Failed to fetch dynamically imported module: /visual-tab.js",
    );
  },
}));

afterEach(() => vi.unstubAllGlobals());

it("contains an import failure, preserves adjacent edits and permits recovery again after a failed save", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const module = Promise.withResolvers<{ default: () => null }>();
  const Fields = lazy(() => module.promise);
  const save = Promise.withResolvers<void>();
  const saveAndReload = vi.fn<(signal?: AbortSignal) => Promise<void>>(
    () => save.promise,
  );
  function Editor() {
    const [value, setValue] = useState("original");
    return (
      <ResourceRecoveryContext value={{ messages: en, saveAndReload }}>
        <input
          aria-label="Phone"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <ResourceErrorBoundary>
          <Suspense fallback={<span>Loading</span>}>
            <Fields />
          </Suspense>
        </ResourceErrorBoundary>
      </ResourceRecoveryContext>
    );
  }
  render(<Editor />);
  const phone = screen.getByRole("textbox", { name: "Phone" });
  fireEvent.change(phone, { target: { value: "unsaved" } });
  await act(async () =>
    module.reject(
      new TypeError("Failed to fetch dynamically imported module: /fields.js"),
    ),
  );
  expect(screen.getByRole("textbox", { name: "Phone" })).toBe(phone);
  expect((phone as HTMLInputElement).value).toBe("unsaved");
  expect(screen.getByRole("alert").textContent).toContain(en.resourceLoadError);
  expect(saveAndReload).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: en.saveAndReload }));
  expect(
    (screen.getByRole("button", { name: en.saving }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(saveAndReload).toHaveBeenCalledOnce();
  await act(async () => save.reject(new Error("Offline")));
  expect(screen.getByRole("alert").textContent).toContain(
    en.resourceRecoverySaveError,
  );
  expect((phone as HTMLInputElement).value).toBe("unsaved");

  const nextSave = Promise.withResolvers<void>();
  saveAndReload.mockImplementation(() => nextSave.promise);
  fireEvent.click(screen.getByRole("button", { name: en.saveAndReload }));
  expect(saveAndReload).toHaveBeenCalledTimes(2);
  await act(async () => nextSave.resolve());
});

it("leaves unexpected render errors to the application error handler", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const failure = new Error("Unexpected render failure");
  function Broken(): never {
    throw failure;
  }
  const onError = vi.fn();
  render(
    <ErrorBoundary fallback={<span>Application error</span>} onError={onError}>
      <ResourceRecoveryContext value={{ messages: en, saveAndReload: vi.fn() }}>
        <ResourceErrorBoundary>
          <Broken />
        </ResourceErrorBoundary>
      </ResourceRecoveryContext>
    </ErrorBoundary>,
  );
  expect(onError.mock.calls[0]?.[0]).toBe(failure);
  expect(screen.queryByRole("button", { name: en.saveAndReload })).toBeNull();
});

it("keeps color editor recovery inside its tab when switching away and back", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  const t = getTemplateEditorMessages("en", en);
  const saveAndReload = vi.fn(async () => {});
  render(
    <ResourceRecoveryContext value={{ messages: en, saveAndReload }}>
      <TemplateEditorTabs
        locale="en"
        t={t}
        template={{ ...getBuiltInTemplates(t)[0], isBuiltIn: false }}
        onUpdateTemplate={vi.fn()}
      />
    </ResourceRecoveryContext>,
  );
  const layoutLabel = screen.getByRole("combobox", {
    name: t.basicInfoLayout,
  }).textContent;
  fireEvent.click(screen.getByRole("tab", { name: t.templateVisualTab }));
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(t.resourceLoadError);

  fireEvent.click(screen.getByRole("tab", { name: t.templateLayoutTab }));
  expect(screen.queryByRole("alert")).toBeNull();
  expect(alert.isConnected).toBe(true);
  expect(
    screen.getByRole("combobox", { name: t.basicInfoLayout }).textContent,
  ).toBe(layoutLabel);

  fireEvent.click(screen.getByRole("tab", { name: t.templateVisualTab }));
  expect(screen.getByRole("alert")).toBe(alert);
  fireEvent.click(screen.getByRole("button", { name: t.saveAndReload }));
  await act(async () => {});
  expect(saveAndReload).toHaveBeenCalledOnce();
});
