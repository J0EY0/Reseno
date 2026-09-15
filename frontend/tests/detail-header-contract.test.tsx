import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ResumeDetailWorkspaceHeader } from "@/components/workspace/resume-detail-workspace-header";
import { TemplateDetailWorkspaceHeader } from "@/components/workspace/template-detail-workspace-header";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { defaultMessages as t } from "@/i18n";
import { createDefaultModelConfig } from "@/lib/model-config";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";
import { installPanelBrowserApis } from "./helpers/route-view-fixtures";

let restore: () => void;
beforeEach(() => {
  restore = installPanelBrowserApis();
});
afterEach(() => {
  restore();
  vi.unstubAllGlobals();
});
function workspace(): ResumeDetailWorkspaceModel {
  const item = createResumeDetailItem({ id: "resume-1", documentLocale: "zh" });
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
        modelConfigs: [
          createDefaultModelConfig("en", {
            id: "model-1",
            model: "test-model",
            nickname: "Test model",
            provider: "openai",
          }),
        ],
        panelStatus: null,
        review: null,
        selectedModelConfigId: "model-1",
      },
      openSectionId: null,
      document: { isPreviewReady: true, isSmartFittingOnePage: false },
      hasLoadError: false,
      hasVersionLoadError: false,
      hasTemplateStyleOverrides: false,
      isDuplicatingResume: false,
      isExporting: false,
      isLoading: false,
      leave: { isOpen: false, isResolving: false },
      previewResume: item.resume,
      previewReview: null,
      resolvedTheme: "light",
      resume: item.resume,
      resumeItem: item,
      save: {
        activeVersionId: null,
        changeCount: 0,
        lastSavedAt: null,
        state: "saved",
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
        flushUserSettings: vi.fn(async () => undefined),
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
      saveAndReload: vi.fn(),
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

it("keeps actual detail back buttons at the shared outline size and export menu at trigger width", async () => {
  const model = workspace();
  const view = render(
    <ResumeDetailWorkspaceHeader
      headerRef={{ current: null }}
      locale="en"
      messages={t}
      model={model}
      onLocaleChange={vi.fn()}
    />,
  );
  await act(() => vi.dynamicImportSettled());
  const back = screen.getByRole("button", { name: t.backToResumes });
  expect(back.getAttribute("data-variant")).toBe("outline");
  expect(back.getAttribute("data-size")).toBe("default");
  fireEvent.click(back);
  expect(model.commands.back).toHaveBeenCalledOnce();
  for (const [label, handler] of [
    [t.exportPdf, model.commands.exportPdf],
    [t.exportImages, model.commands.exportImages],
    [t.exportJson, model.commands.exportJson],
  ] as const) {
    const trigger = screen.getByRole("button", { name: t.export });
    expect(trigger.classList.contains("min-w-32")).toBe(true);
    fireEvent.keyDown(trigger, { key: "Enter" });
    const menu = screen.getByRole("menu");
    for (const token of [
      "w-[var(--radix-dropdown-menu-trigger-width)]",
      "min-w-[var(--radix-dropdown-menu-trigger-width)]",
    ])
      expect(menu.classList.contains(token)).toBe(true);
    fireEvent.click(screen.getByRole("menuitem", { name: label }));
    expect(handler).toHaveBeenCalledOnce();
  }
  view.unmount();
  const onBack = vi.fn();
  render(
    <TemplateDetailWorkspaceHeader
      changeCount={0}
      headerRef={{ current: null }}
      lastSavedAt={null}
      locale="en"
      messages={t}
      onBack={onBack}
      onLocaleChange={vi.fn()}
      onLogout={vi.fn()}
      onSave={vi.fn(async () => undefined)}
      onThemeChange={vi.fn()}
      resolvedTheme="light"
      saveState="saved"
      template={createResumeDetailTemplate("custom")}
    />,
  );
  const templateBack = screen.getByRole("button", { name: t.backToTemplates });
  expect(templateBack.getAttribute("data-variant")).toBe("outline");
  expect(templateBack.getAttribute("data-size")).toBe("default");
  fireEvent.click(templateBack);
  expect(onBack).toHaveBeenCalledOnce();
});
