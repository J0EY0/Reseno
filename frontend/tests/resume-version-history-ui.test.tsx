import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { SaveStatusButton } from "@/components/save-status-button";
import { ResumeHistoryToolbar } from "@/components/workspace/resume-history-toolbar";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restore: () => void;
beforeEach(() => {
  restore = installPanelBrowserApis();
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});

it("distinguishes the viewed history from the current version and requires explicit restoration", () => {
  const old = { versionId: "v1", savedAt: "2026-09-01T10:00:00Z" };
  const current = { versionId: "v2", savedAt: "2026-09-02T10:00:00Z" };
  const onSave = vi.fn();
  const onRestore = vi.fn();
  const onReturn = vi.fn();
  const props = {
    locale: "en" as const,
    historyVersion: { ...old, resume: createResumeDetailItem() },
    isRestoring: false,
    hasRestoreError: false,
    onRestore,
    onReturn,
  };
  const { rerender } = render(
    <>
      <SaveStatusButton
        locale="en"
        label="Save"
        savingText="Saving"
        savedText="Saved"
        unsavedText="Unsaved"
        lastSavedLabel="Last saved"
        state="saved"
        hasUnsavedChanges={false}
        lastSavedAt={current.savedAt}
        versions={[current, old]}
        activeVersionId={current.versionId}
        versionsLabel="Versions"
        currentVersionLabel="Current"
        noVersionsText="No versions"
        onSave={onSave}
        onSelectVersion={vi.fn()}
        history={old}
      />
      <section className="resume-preview-card">
        <ResumeHistoryToolbar {...props} />
        <div
          data-slot="document-canvas-viewport"
          tabIndex={0}
          role="region"
          aria-label="Resume preview"
        />
      </section>
    </>,
  );
  expect(
    (screen.getByRole("button", { name: "Save" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  expect(screen.getAllByRole("status")[0].textContent).toContain(
    "Viewing historical version",
  );
  fireEvent.click(screen.getByRole("button", { name: "Versions" }));
  const entries = within(
    screen.getByRole("dialog", { name: "Versions" }),
  ).getAllByRole("button");
  expect(entries[0].textContent).toContain("Current");
  expect(entries[1].textContent).toContain("Viewing");
  expect(entries[1].textContent).not.toContain("Current");
  fireEvent.click(screen.getByRole("button", { name: "Restore this version" }));
  expect(onRestore).toHaveBeenCalledOnce();
  expect(onSave).not.toHaveBeenCalled();
  const returnButton = screen.getByRole("button", { name: "Back to latest" });
  const preview = screen.getByRole("region", { name: "Resume preview" });
  const focusPreview = vi.spyOn(preview, "focus");
  onReturn.mockImplementation(() =>
    expect(document.activeElement).toBe(preview),
  );
  returnButton.focus();
  fireEvent.click(returnButton);
  expect(onReturn).toHaveBeenCalledOnce();
  expect(focusPreview).toHaveBeenCalledWith({ preventScroll: true });
  expect(document.activeElement).toBe(preview);
  rerender(<ResumeHistoryToolbar {...props} isRestoring />);
  expect(
    (
      screen.getByRole("button", {
        name: "Restoring version…",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (
      screen.getByRole("button", {
        name: "Back to latest",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  rerender(<ResumeHistoryToolbar {...props} hasRestoreError />);
  expect(screen.getByRole("alert").textContent).toContain(
    "Could not restore this version",
  );
  expect(
    (
      screen.getByRole("button", {
        name: "Restore this version",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(false);
});
