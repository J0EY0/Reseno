import {
  createEvent,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SaveStatusButton } from "@/components/save-status-button";
import { GalleryPagination } from "@/components/gallery-pagination";
import { defaultMessages as t } from "@/i18n";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restore: () => void;
beforeEach(() => {
  restore = installPanelBrowserApis();
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});
it("keeps save direct and version history open through selection and status announcements", () => {
  const props = {
    locale: "en" as const,
    label: "Save",
    savingText: "Saving",
    savedText: "Saved",
    unsavedText: "Unsaved",
    lastSavedLabel: "Last saved",
    state: "idle" as "idle" | "saving" | "saved",
    hasUnsavedChanges: true,
    lastSavedAt: null as string | null,
    versions: [
      { versionId: "v1", savedAt: "2026-09-01T10:00:00Z" },
      { versionId: "v2", savedAt: "2026-09-02T10:00:00Z" },
    ],
    activeVersionId: "v1",
    versionsLabel: "Versions",
    currentVersionLabel: "Current",
    noVersionsText: "No versions",
    onSave: vi.fn(),
    onSelectVersion: vi.fn(),
  };
  const { rerender } = render(<SaveStatusButton {...props} />);
  const save = screen.getByRole("button", { name: "Save" });
  fireEvent.click(save);
  expect(props.onSave).toHaveBeenCalledOnce();
  expect(screen.queryByRole("dialog")).toBeNull();
  const trigger = screen.getByRole("button", { name: "Versions" });
  expect(trigger.tabIndex).toBe(0);
  fireEvent.click(trigger);
  const history = screen.getByRole("dialog", { name: "Versions" });
  const entries = within(history).getAllByRole("button");
  expect(entries).toHaveLength(2);
  expect(entries[0].textContent).toContain("Current");
  entries[1].focus();
  fireEvent.click(entries[1]);
  expect(props.onSelectVersion).toHaveBeenCalledExactlyOnceWith("v2");
  expect(screen.getByRole("dialog", { name: "Versions" })).toBe(history);
  expect(document.activeElement).toBe(entries[1]);
  const announcement = screen.getByRole("status");
  expect(announcement.getAttribute("aria-live")).toBe("polite");
  expect(announcement.getAttribute("aria-atomic")).toBe("true");
  expect(announcement.textContent).toBe("Unsaved");
  rerender(<SaveStatusButton {...props} state="saving" />);
  expect(announcement.textContent).toBe("Saving");
  expect((save as HTMLButtonElement).disabled).toBe(true);
  expect(document.activeElement).toBe(entries[1]);
  rerender(
    <SaveStatusButton
      {...props}
      state="saved"
      hasUnsavedChanges={false}
      lastSavedAt="2026-09-02T10:00:00Z"
    />,
  );
  expect(announcement.textContent).toMatch(/^Saved · Last saved: /);
  expect(screen.getByRole("dialog", { name: "Versions" })).toBe(history);
});
it.each(["metaKey", "ctrlKey", "shiftKey", "altKey", "middle"] as const)(
  "preserves native pagination link behavior for %s",
  (modifier) => {
    const change = vi.fn();
    render(
      <MemoryRouter initialEntries={["/resume?page=2&q=search#list"]}>
        <GalleryPagination
          currentPage={2}
          totalPages={4}
          t={t}
          onPageChange={change}
        />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "3" });
    expect(link.getAttribute("href")).toBe("/resume?page=3&q=search#list");
    expect(screen.getByRole("link", { name: "1" }).getAttribute("href")).toBe(
      "/resume?q=search#list",
    );
    const event = createEvent.click(
      link,
      modifier === "middle" ? { button: 1 } : { button: 0, [modifier]: true },
    );
    let preventedByComponent = true;
    document.addEventListener(
      "click",
      (native) => {
        preventedByComponent = native.defaultPrevented;
        native.preventDefault();
      },
      { once: true },
    );
    fireEvent(link, event);
    expect(preventedByComponent).toBe(false);
    expect(change).not.toHaveBeenCalled();
  },
);
it("handles plain pagination once while keeping active and unavailable pages inert", () => {
  const change = vi.fn();
  const view = (disabled = false) => (
    <MemoryRouter initialEntries={["/templates?tab=all#list"]}>
      <GalleryPagination
        currentPage={1}
        totalPages={7}
        t={t}
        onPageChange={change}
        disabled={disabled}
      />
    </MemoryRouter>
  );
  const { rerender } = render(view());
  const next = screen.getByRole("link", { name: "2" });
  expect(fireEvent.click(next)).toBe(false);
  expect(change).toHaveBeenCalledExactlyOnceWith(2);
  fireEvent.click(screen.getByRole("link", { name: "1" }));
  expect(change).toHaveBeenCalledTimes(1);
  expect(
    screen.getByLabelText(t.paginationPrevious).getAttribute("aria-disabled"),
  ).toBe("true");
  expect(
    screen.getByLabelText(t.paginationPrevious).getAttribute("href"),
  ).toBeNull();
  rerender(view(true));
  const unavailable = screen.getByText("2");
  expect(unavailable.getAttribute("href")).toBeNull();
  expect(unavailable.tabIndex).toBe(-1);
  expect(fireEvent.click(unavailable)).toBe(false);
  expect(change).toHaveBeenCalledTimes(1);
});
