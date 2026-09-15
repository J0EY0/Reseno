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
import { RecycleBinPanel } from "@/components/recycle-bin-panel";
import type { RecycleBinPanelProps } from "@/components/recycle-bin-types";
import { defaultMessages as t } from "@/i18n";
import { createTemplateImageElement } from "@/lib/templates";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";
import {
  createTrashProps,
  installPanelBrowserApis,
} from "./helpers/route-view-fixtures";
import { deferred } from "./helpers/pdf-browser-fixtures";

let restoreBrowserApis: () => void;
beforeEach(() => {
  restoreBrowserApis = installPanelBrowserApis();
});
afterEach(() => {
  cleanup();
  restoreBrowserApis();
  vi.unstubAllGlobals();
});
function renderTrash(props: RecycleBinPanelProps, query = "") {
  const router = createMemoryRouter(
    [{ path: "*", element: <RecycleBinPanel {...props} /> }],
    { initialEntries: [`/trash${query}`] },
  );
  return { ...render(<RouterProvider router={router} />), router };
}
function openActions(title: string) {
  const trigger = screen.getByRole("button", {
    name: `${t.actions}: ${title}`,
  });
  fireEvent.keyDown(trigger, { key: "Enter" });
  return trigger;
}

it.each(["resume", "template"] as const)(
  "selects only the current %s page, restores its IDs, and defers deletion until success",
  async (kind) => {
    const props = createTrashProps();
    const restore = vi.fn(async () => true);
    const remove = vi.fn<(...args: string[][]) => Promise<boolean>>();
    if (kind === "resume") {
      props.onRestoreResume = restore;
      props.onDeleteResumeForever = remove;
    } else {
      props.onRestoreTemplate = restore;
      props.onDeleteTemplateForever = remove;
    }
    const { container, router } = renderTrash(
      props,
      kind === "template" ? "?tab=templates&keep=1" : "?keep=1",
    );
    const panel = container.querySelector('[data-slot="recycle-bin-panel"]')!;
    expect(panel.classList.contains("bg-muted/35")).toBe(true);
    const list = container.querySelector('[data-slot="trash-list-content"]')!;
    expect(list.classList.contains("min-h-[390px]")).toBe(true);
    expect(list.classList.contains("overflow-hidden")).toBe(true);
    expect(screen.getAllByRole("row")).toHaveLength(7);
    const tabs = screen.getAllByRole("tab");
    for (const tab of tabs) {
      expect(tab.classList.contains("group/trash-tab")).toBe(true);
      const badge = tab.querySelector('[data-slot="badge"]')!;
      expect(badge.textContent).toBe("7");
      expect(badge.getAttribute("data-variant")).toBe("secondary");
      expect(
        badge.classList.contains(
          "group-data-[state=inactive]/trash-tab:bg-background",
        ),
      ).toBe(true);
    }
    const deletedColumn = screen.getByRole("columnheader", {
      name: t.recycleBinDeletedAtLabel,
    });
    expect(
      deletedColumn.firstElementChild?.classList.contains("text-center"),
    ).toBe(true);
    const dateCell = screen.getAllByRole("row")[1].querySelectorAll("td")[2];
    expect(dateCell.firstElementChild?.classList.contains("text-center")).toBe(
      true,
    );
    const bulk = container.querySelector<HTMLElement>(
      '[data-slot="trash-bulk-actions"]',
    )!;
    expect(bulk.getAttribute("aria-hidden")).toBe("true");
    expect(bulk.hasAttribute("inert")).toBe(true);
    expect(within(bulk).queryByRole("button")).toBeNull();
    const first = screen.getAllByRole("checkbox")[1];
    fireEvent.click(first);
    expect(
      screen.getAllByRole("checkbox")[1].getAttribute("aria-checked"),
    ).toBe("true");
    expect(bulk.getAttribute("aria-hidden")).toBe("false");
    expect(bulk.hasAttribute("inert")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: t.deleteForever }));
    expect(screen.getByRole("alertdialog")).toBeTruthy();
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: t.cancel,
      }),
    );
    expect(screen.queryByRole("alertdialog")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: t.selectAll }));
    fireEvent.click(screen.getByRole("button", { name: t.restoreSelected }));
    await waitFor(() =>
      expect(restore).toHaveBeenCalledExactlyOnceWith(
        Array.from({ length: 6 }, (_, i) => `${kind}-${i}`),
      ),
    );
    await waitFor(() => expect(bulk.getAttribute("aria-hidden")).toBe("true"));
    fireEvent.click(screen.getByRole("link", { name: "2" }));
    expect(router.state.location.search).toContain("page=2");
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(
      screen
        .getByRole("checkbox", { name: t.selectAll })
        .getAttribute("aria-checked"),
    ).toBe("false");
    const title = `${kind === "resume" ? "Resume" : "Template"} 6`;
    openActions(title);
    const menu = screen.getByRole("menu");
    expect(menu.classList.contains("w-32")).toBe(true);
    expect(menu.classList.contains("whitespace-nowrap")).toBe(true);
    const groups = within(menu).getAllByRole("group");
    expect(
      within(groups[0])
        .getAllByRole("menuitem")
        .map((item) => item.textContent),
    ).toEqual([t.preview, t.restore]);
    expect(within(groups[1]).getByRole("menuitem").textContent).toBe(
      t.deleteTrashItemAction,
    );
    expect(menu.querySelector('[role="separator"]')).not.toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: t.restore }));
    await waitFor(() =>
      expect(restore).toHaveBeenLastCalledWith([`${kind}-6`]),
    );
    expect(restore).toHaveBeenCalledTimes(2);
    openActions(title);
    const deleteItem = screen.getByRole("menuitem", {
      name: t.deleteTrashItemAction,
    });
    expect(deleteItem.getAttribute("data-variant")).toBe("destructive");
    fireEvent.click(deleteItem);
    const dialog = screen.getByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", {
      name: t.deleteForever,
    });
    const gate = deferred<boolean>();
    remove.mockReturnValueOnce(gate.promise);
    fireEvent.click(confirm);
    expect(remove).toHaveBeenCalledExactlyOnceWith([`${kind}-6`]);
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    expect(
      (
        within(dialog).getByRole("button", {
          name: t.cancel,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("alertdialog")).toBe(dialog);
    await act(async () => gate.resolve(false));
    expect(screen.getByRole("alertdialog")).toBe(dialog);
    expect((confirm as HTMLButtonElement).disabled).toBe(false);
    remove.mockResolvedValueOnce(true);
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(remove).toHaveBeenCalledTimes(2);
  },
);

it.each(["resume", "template"] as const)(
  "opens the real %s preview with a static focus target and restores row-menu focus",
  async (kind) => {
    const props = createTrashProps(1);
    if (kind === "template")
      props.deletedTemplates[0].layout.images = [
        createTemplateImageElement(1, "Brand"),
      ];
    const { container } = renderTrash(
      props,
      kind === "template" ? "?tab=templates" : "",
    );
    const thumbnail = container.querySelector(
      '[aria-hidden="true"] .pointer-events-none.absolute.left-0',
    )!;
    expect(thumbnail).not.toBeNull();
    expect(thumbnail.closest('[aria-hidden="true"]')).not.toBeNull();
    const title = kind === "resume" ? "Resume 0" : "Template 0";
    if (kind === "template")
      expect(
        container.querySelector('[data-template-image-frame="true"]'),
      ).not.toBeNull();
    openActions(title);
    fireEvent.click(screen.getByRole("menuitem", { name: t.preview }));
    const dialog = screen.getByRole("dialog");
    const heading = within(dialog).getByRole("heading", {
      name: `${t.preview}: ${title}`,
    });
    expect(heading.classList.contains("sr-only")).toBe(true);
    expect(heading.tabIndex).toBe(-1);
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(
      dialog
        .querySelector('[data-slot="dialog-description"]')
        ?.classList.contains("sr-only"),
    ).toBe(true);
    for (const token of [
      "rounded-(--radius-preview)",
      "border-0",
      "bg-transparent",
      "shadow-none",
    ])
      expect(dialog.classList.contains(token)).toBe(true);
    expect(dialog.querySelector('[data-slot="dialog-header"]')).toBeNull();
    expect(
      dialog.querySelector('[data-slot="trash-preview-dialog"]'),
    ).not.toBeNull();
    await act(() => vi.dynamicImportSettled());
    await waitFor(() =>
      expect(
        dialog.querySelector('[data-export-root="resume-page"]'),
      ).not.toBeNull(),
    );
    const page = dialog.querySelector<HTMLElement>(
      '[data-export-root="resume-page"]',
    )!;
    if (kind === "resume") {
      expect(page.style.fontSize).toBe("18px");
      expect(page.style.getPropertyValue("--resume-page-bg")).toBe("#abcdef");
    } else
      expect(page.style.fontSize).toBe(
        `${props.deletedTemplates[0].typography.fontSize}px`,
      );
    fireEvent.click(within(dialog).getByRole("button", { name: t.close }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("button", { name: `${t.actions}: ${title}` }),
      ),
    );
  },
);

it("preserves the empty-list baseline and concise destructive menu labels in both locales", () => {
  const { container, router } = renderTrash(createTrashProps(0));
  expect(screen.getByText(t.emptyResumeTrash)).toBeTruthy();
  expect(
    container
      .querySelector('[data-slot="empty"]')
      ?.classList.contains("min-h-[390px]"),
  ).toBe(true);
  fireEvent.mouseDown(screen.getByRole("tab", { name: /Templates/ }), {
    button: 0,
  });
  expect(router.state.location.search).toBe("?tab=templates");
  expect(screen.getByText(t.emptyTemplateTrash)).toBeTruthy();
  expect(en.deleteTrashItemAction).toBe("Delete");
  expect(zh.deleteTrashItemAction).toBe("删除");
});
