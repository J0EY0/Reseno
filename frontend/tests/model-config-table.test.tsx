import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { BrowserRouter } from "react-router-dom";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { defaultMessages as t } from "@/i18n";
import { ModelConfigPanel } from "@/components/model-config-panel";
import { ModelConfigTable } from "@/components/models/model-config-table";
import {
  useModelConfigTableSelection,
  resolveSelectedModelConfigIds,
} from "@/components/models/use-model-config-table-selection";
import { createDefaultModelConfig } from "@/lib/model-config";
import type { ModelConfig } from "@/types/resume";

const request = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  requestApi: request,
}));
const configs = Array.from({ length: 12 }, (_, index) => ({
  ...createDefaultModelConfig("en"),
  id: `model-${index}`,
  nickname: `Model ${index}`,
  providerKind: "local" as const,
  provider: "ollama",
  model: `test-${index}`,
}));
const provider = {
  id: "ollama",
  kind: "local",
  label: "Ollama",
  iconProvider: "ollama",
  defaultBaseUrl: "http://localhost:11434/v1",
  authRequired: false,
  apiFamily: "openai_chat",
  officialUrl: "",
  supportsModelDiscovery: false,
  supportsCustomCapabilities: true,
  supportsTools: true,
  supportsStreaming: true,
};
function wrapper({ children }: { children: ReactNode }) {
  return <BrowserRouter>{children}</BrowserRouter>;
}
beforeEach(() => {
  history.replaceState(null, "", "/models?q=kept");
  request.mockReset().mockImplementation(async (route) => {
    if (route === "/api/model-providers") return { providers: [provider] };
    throw new Error(`Unexpected request ${route}`);
  });
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  history.replaceState(null, "", "/");
});

it("retains selected IDs in selection order while pruning missing rows and suppressing old-page selection", () => {
  expect(
    resolveSelectedModelConfigIds(
      { page: 2, modelConfigIds: ["model-0", "removed", "model-1"] },
      2,
      [configs[1], configs[0]],
    ),
  ).toEqual(["model-0", "model-1"]);
  expect(
    resolveSelectedModelConfigIds(
      { page: 1, modelConfigIds: ["model-0", "model-1"] },
      2,
      configs,
    ),
  ).toEqual([]);
});
it("paginates ten rows, clears selection on PUSH and POP, and clamps missing pages", () => {
  const renders: { page: number; ids: string[] }[] = [];
  const { result, rerender } = renderHook(
    ({ values }) => {
      const selection = useModelConfigTableSelection(values);
      renders.push({
        page: selection.currentPage,
        ids: selection.selectedModelConfigIds,
      });
      return selection;
    },
    { wrapper, initialProps: { values: configs } },
  );
  expect(result.current.totalPages).toBe(2);
  expect(result.current.pageConfigs).toEqual(configs.slice(0, 10));
  act(() => result.current.onRowSelectionChange({ "model-0": true }));
  expect(result.current.rowSelection).toEqual({ "model-0": true });
  renders.length = 0;
  act(() => result.current.changePage(2));
  expect(location.search).toBe("?q=kept&page=2");
  expect(result.current.pageConfigs).toEqual(configs.slice(10));
  expect(result.current.rowSelection).toEqual({});
  expect(
    renders.every((value) => value.page !== 2 || value.ids.length === 0),
  ).toBe(true);
  act(() => result.current.onRowSelectionChange({ "model-10": true }));
  renders.length = 0;
  act(() => {
    history.replaceState(null, "", "/models?q=kept");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  expect(result.current.currentPage).toBe(1);
  expect(result.current.selectedModelConfigIds).toEqual([]);
  expect(
    renders.every((value) => value.page !== 1 || value.ids.length === 0),
  ).toBe(true);
  act(() => {
    history.replaceState(null, "", "/models?q=kept&page=2");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  expect(result.current.selectedModelConfigIds).toEqual([]);
  rerender({ values: configs.slice(0, 2) });
  expect(result.current.currentPage).toBe(1);
  expect(result.current.pageConfigs).toEqual(configs.slice(0, 2));
});
it("uses persistent IDs for checked rows, supports partial and page selection, and dispatches row actions", async () => {
  const onEdit = vi.fn();
  const onDelete = vi.fn();
  function Table() {
    const selection = useModelConfigTableSelection(configs.slice(0, 2));
    return (
      <ModelConfigTable
        locale="en"
        t={t}
        configs={selection.pageConfigs}
        rowSelection={selection.rowSelection}
        onRowSelectionChange={selection.onRowSelectionChange}
        deletingModelConfigId={null}
        enteringModelConfigId="model-1"
        disabled={false}
        onEdit={onEdit}
        onDelete={onDelete}
      />
    );
  }
  const { container } = render(<Table />, { wrapper });
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: `${t.selectItems}: Model 1 (test-1)`,
    }),
  );
  expect(
    screen
      .getByRole("checkbox", { name: t.selectAll })
      .getAttribute("aria-checked"),
  ).toBe("mixed");
  expect(
    screen
      .getByText("Model 1 (test-1)")
      .closest("tr")
      ?.getAttribute("data-state"),
  ).toBe("selected");
  expect(
    screen
      .getByText("Model 0 (test-0)")
      .closest("tr")
      ?.getAttribute("data-state"),
  ).not.toBe("selected");
  expect(
    screen.getByText("Model 1 (test-1)").closest("tr")?.className,
  ).toContain("fade-in");
  expect(
    screen.getByText("Model 0 (test-0)").closest("tr")?.className,
  ).not.toContain("fade-in");
  fireEvent.click(screen.getByRole("checkbox", { name: t.selectAll }));
  expect(
    screen
      .getByRole("checkbox", { name: t.selectAll })
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(container.querySelectorAll('tr[data-state="selected"]')).toHaveLength(
    2,
  );
  const trigger = screen.getAllByRole("button", { name: t.actions })[1];
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Edit" }));
  expect(onEdit).toHaveBeenCalledExactlyOnceWith(configs[1], trigger);
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
  expect(onDelete).toHaveBeenCalledExactlyOnceWith("model-1");
});
function Panel({ initial = configs.slice(0, 2) }: { initial?: ModelConfig[] }) {
  const [values, setValues] = useState(initial);
  return (
    <ModelConfigPanel
      locale="en"
      t={t}
      configs={values}
      onChange={(update) => {
        const next = update(values);
        setValues(next);
        return next;
      }}
    />
  );
}
it("deletes a selected batch atomically, keeps confirmation pending, and clears selection after success", async () => {
  const deleted = Promise.withResolvers<{ ids: string[] }>();
  request.mockReturnValue(deleted.promise);
  const { container } = render(<Panel />, { wrapper });
  const add = screen.getByRole("button", { name: t.addModelConfig });
  const actions = container.querySelector(
    '[data-slot="model-config-bulk-actions"]',
  )!;
  expect(actions.getAttribute("aria-hidden")).toBe("true");
  expect(actions.hasAttribute("inert")).toBe(true);
  expect(actions.querySelector("button")?.tabIndex).toBe(-1);
  fireEvent.click(screen.getByRole("checkbox", { name: t.selectAll }));
  expect(actions.getAttribute("aria-hidden")).toBe("false");
  expect(actions.hasAttribute("inert")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: t.bulkDelete }));
  const confirmation = screen.getByRole("alertdialog", {
    name: t.deleteModelConfigsConfirmTitle,
  });
  fireEvent.click(
    within(confirmation).getByRole("button", { name: t.bulkDelete }),
  );
  expect(request).toHaveBeenCalledExactlyOnceWith(
    "/api/model-configs/bulk-delete",
    { method: "POST", body: { ids: ["model-0", "model-1"] } },
  );
  expect(screen.getByRole("alertdialog")).toBe(confirmation);
  expect(
    within(confirmation)
      .getByRole("button", { name: t.cancel })
      .hasAttribute("disabled"),
  ).toBe(true);
  await act(async () => deleted.resolve({ ids: ["model-0", "model-1"] }));
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(screen.getByText(t.emptyModelConfigs)).not.toBeNull();
  expect(screen.getByRole("button", { name: t.addModelConfig })).toBe(add);
  expect(actions.getAttribute("aria-hidden")).toBe("true");
  expect(request).toHaveBeenCalledOnce();
});
it("keeps an edit dialog outside the row menu, restores focus, and discards the previous edit session on reopening", async () => {
  render(<Panel />, { wrapper });
  const trigger = screen.getAllByRole("button", { name: t.actions })[0];
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Edit" }));
  const dialog = await screen.findByRole("dialog");
  expect(screen.queryByRole("menu")).toBeNull();
  await waitFor(() =>
    expect(
      within(dialog)
        .getByRole("button", { name: t.saveModelConfig })
        .hasAttribute("disabled"),
    ).toBe(false),
  );
  fireEvent.change(within(dialog).getByLabelText(t.displayName), {
    target: { value: "Discard me" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: t.cancel }));
  await waitFor(() => expect(document.activeElement).toBe(trigger));
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "Edit" }));
  const reopened = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(
      (within(reopened).getByLabelText(t.displayName) as HTMLInputElement)
        .value,
    ).toBe("Model 0"),
  );
});
