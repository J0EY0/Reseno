import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ResumeDetailLeaveDialog } from "@/components/workspace/resume-detail-leave-dialog";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { TemplateDetailLeaveDialog } from "@/components/workspace/template-detail-leave-dialog";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";

import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

function createModel(): ResumeDetailWorkspaceModel {
  const item = createResumeDetailItem();
  const template = createResumeDetailTemplate("minimal");
  return {
    state: {
      activeTemplate: template,
      previewTemplate: template,
      previewTypography: item.typography,
      agent: {
        draft: null,
        draftState: null,
        isPanelCollapsed: true,
        modelConfigs: [],
        panelStatus: null,
        review: null,
        selectedModelConfigId: "",
      },
      openSectionId: null,
      document: { isPreviewReady: true, isSmartFittingOnePage: false },
      hasLoadError: false,
      hasVersionLoadError: false,
      hasTemplateStyleOverrides: false,
      isDuplicatingResume: false,
      isExporting: false,
      isLoading: false,
      leave: { isOpen: true, isResolving: false },
      previewResume: item.resume,
      previewReview: null,
      resolvedTheme: "light",
      resume: item.resume,
      resumeItem: item,
      save: {
        activeVersionId: null,
        changeCount: 3,
        lastSavedAt: null,
        state: "idle",
        versions: [],
      },
      showSkeleton: false,
      template: "minimal",
      templates: [template],
      theme: "light",
      title: { draft: item.title, isOpen: false },
      typography: item.typography,
    },
    commands: {
      agent: {
        applyDraft: vi.fn(async () => null),
        changeSelectedModelConfig: vi.fn(),
        discardDraft: vi.fn(async () => null),
        flushUserSettings: vi.fn(async () => {}),
        openModelSettings: vi.fn(),
        previewEdits: vi.fn(),
        reconcileDraft: vi.fn(),
        reportPanelStatus: vi.fn(),
        rollbackDraft: vi.fn(),
        setPanelCollapsed: vi.fn(),
      },
      applyTemplate: vi.fn(),
      back: vi.fn(),
      changeTheme: vi.fn(),
      changeTitleDraft: vi.fn(),
      changeView: vi.fn(),
      duplicateResume: vi.fn(),
      exportImages: vi.fn(),
      exportJson: vi.fn(),
      exportPdf: vi.fn(),
      fitOnePage: vi.fn(),
      logout: vi.fn(),
      onPreviewReadyChange: vi.fn(),
      preloadView: vi.fn(),
      restoreTemplateDefaults: vi.fn(),
      retryLoad: vi.fn(),
      save: vi.fn(),
      saveAndReload: vi.fn(async () => {}),
      saveTitle: vi.fn(),
      selectVersion: vi.fn(),
      addSection: vi.fn(),
      removeSection: vi.fn(),
      toggleSection: vi.fn(),
      updateContent: vi.fn(),
      setTitleDialogOpen: vi.fn(),
      updateTemplateSettings: vi.fn(),
      updateTypography: vi.fn(),
      cancelLeave: vi.fn(),
      discardAndLeave: vi.fn(),
      saveAndLeave: vi.fn(),
    },
  };
}

describe.each(["resume", "template"])("%s leave dialog", (kind) => {
  it.each([en, zh])(
    "keeps the save action busy and unavailable until it can be retried in $saving",
    (messages) => {
      const onCancel = vi.fn();
      const onDiscard = vi.fn(async () => {});
      const onSave = vi.fn(async () => {});
      const model = createModel();
      const view = (isResolving: boolean) =>
        kind === "template" ? (
          <TemplateDetailLeaveDialog
            changeCount={3}
            isOpen
            isResolving={isResolving}
            messages={messages}
            onCancel={onCancel}
            onDiscard={onDiscard}
            onSave={onSave}
          />
        ) : (
          <ResumeDetailLeaveDialog
            messages={messages}
            model={{
              ...model,
              state: { ...model.state, leave: { isOpen: true, isResolving } },
              commands: {
                ...model.commands,
                cancelLeave: onCancel,
                discardAndLeave: onDiscard,
                saveAndLeave: onSave,
              },
            }}
          />
        );
      const { rerender } = render(view(false));
      const dialog = screen.getByRole("dialog", {
        name: messages.unsavedChangesTitle,
      });
      const save = within(dialog).getByRole<HTMLButtonElement>("button", {
        name: messages.unsavedChangesSaveAndLeave,
      });
      fireEvent.click(save);
      expect(onSave).toHaveBeenCalledOnce();

      rerender(view(true));
      expect(
        within(dialog).getByRole("button", { name: messages.saving }),
      ).toBe(save);
      expect(save.getAttribute("aria-busy")).toBe("true");
      expect(save.disabled).toBe(true);
      fireEvent.click(save);
      for (const name of [
        messages.unsavedChangesContinueEditing,
        messages.unsavedChangesDiscard,
      ]) {
        const button = within(dialog).getByRole<HTMLButtonElement>("button", {
          name,
        });
        expect(button.disabled).toBe(true);
        fireEvent.click(button);
      }
      fireEvent.click(
        within(dialog).getByRole("button", { name: messages.close }),
      );
      fireEvent.keyDown(dialog, { key: "Escape" });
      expect(onSave).toHaveBeenCalledOnce();
      expect(onDiscard).not.toHaveBeenCalled();
      expect(onCancel).not.toHaveBeenCalled();
      expect(screen.getByRole("dialog")).toBe(dialog);

      rerender(view(false));
      expect(
        within(dialog).getByRole("button", {
          name: messages.unsavedChangesSaveAndLeave,
        }),
      ).toBe(save);
      expect(save.getAttribute("aria-busy")).not.toBe("true");
      expect(save.disabled).toBe(false);
      fireEvent.click(save);
      expect(onSave).toHaveBeenCalledTimes(2);
    },
  );
});
