import { act, fireEvent, render } from "@testing-library/react";
import type { ComponentProps, ReactNode } from "react";
import { expect, it, vi } from "vitest";

import type { ResumeEditorPane } from "@/components/editor/resume-editor-pane";
import type { DocumentCanvas } from "@/components/preview/document-canvas";
import { ResumeDetailWorkspaceView } from "@/components/workspace/resume-detail-workspace-view";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { createResumeSection } from "@/lib/resume-sections";
import { getMessagesSync } from "@/i18n";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";

const mocks = vi.hoisted(() => ({
  preview: vi.fn<(props: ComponentProps<typeof DocumentCanvas>) => ReactNode>(),
  editor:
    vi.fn<(props: ComponentProps<typeof ResumeEditorPane>) => ReactNode>(),
  module: Promise.withResolvers<{ default: typeof DocumentCanvas }>(),
}));
vi.mock("@/components/editor/resume-editor-pane", () => ({
  ResumeEditorPane: mocks.editor,
}));
vi.mock("@/components/preview/document-canvas-loader", () => ({
  loadDocumentCanvas: () => mocks.module.promise,
}));
vi.mock("@/components/app-toaster", () => ({ AppToaster: () => null }));
vi.mock("@/components/ui/sidebar", () => ({
  SidebarProvider: ({ children }: { children: ReactNode }) => children,
  SidebarInset: (props: ComponentProps<"main">) => <main {...props} />,
}));
vi.mock("@/components/workspace/resume-detail-agent-host", () => ({
  ResumeDetailAgentHost: () => null,
  ResumeDetailAgentToggle: () => null,
}));
vi.mock("@/components/workspace/resume-detail-workspace-header", () => ({
  ResumeDetailWorkspaceHeader: () => null,
}));
vi.mock("@/components/workspace/resume-detail-leave-dialog", () => ({
  ResumeDetailLeaveDialog: () => null,
}));
vi.mock("@/components/workspace/resume-detail-title-dialog", () => ({
  ResumeDetailTitleDialog: () => null,
}));
vi.mock("@/components/workspace/resume-workspace-columns", () => ({
  ResumeWorkspaceColumns: ({
    editor,
    preview,
    agent,
  }: {
    editor: ReactNode;
    preview: ReactNode;
    agent: ReactNode;
  }) => (
    <>
      {editor}
      {preview}
      {agent}
    </>
  ),
}));
vi.mock("@/components/workspace-skeletons", () => ({
  WorkspacePreviewSkeleton: () => <div>Preview loading</div>,
}));

it("preserves loading states, passes document operations and separates version errors from route errors", async () => {
  const resumeItem = createResumeDetailItem();
  const commands = {
    updateContent: vi.fn(),
    toggleSection: vi.fn(),
    addSection: vi.fn(),
    removeSection: vi.fn(),
    onPreviewReadyChange: vi.fn(),
    retryLoad: vi.fn(),
  };
  const state = {
    agent: { isPanelCollapsed: true },
    document: { measurementKey: {} },
    openSectionId: "skills",
    previewResume: resumeItem.resume,
    previewTemplate: { id: "minimal" },
    previewTypography: resumeItem.typography,
    resume: resumeItem.resume,
    resumeItem,
    showSkeleton: true,
    hasLoadError: false,
    hasVersionLoadError: false,
    theme: "light",
  };
  const model = { commands, state } as unknown as ResumeDetailWorkspaceModel;
  const messages = getMessagesSync("en");
  mocks.editor.mockReturnValue(null);
  mocks.preview.mockReturnValue(<section>Ready preview</section>);
  const props = {
    locale: "en" as const,
    messages,
    model,
    onLocaleChange: vi.fn(),
    previewRef: { current: null },
  };
  const view = render(<ResumeDetailWorkspaceView {...props} />);
  expect(view.getByText("Preview loading")).toBeTruthy();
  expect(mocks.editor.mock.lastCall?.[0].showSkeleton).toBe(true);
  expect(mocks.preview).not.toHaveBeenCalled();
  state.showSkeleton = false;
  view.rerender(<ResumeDetailWorkspaceView {...props} />);
  expect(view.getByText("Preview loading")).toBeTruthy();
  expect(mocks.preview).not.toHaveBeenCalled();
  await act(async () =>
    mocks.module.resolve({
      default: mocks.preview as unknown as typeof DocumentCanvas,
    }),
  );
  expect(view.getByText("Ready preview")).toBeTruthy();
  const editor = mocks.editor.mock.lastCall![0];
  expect(editor.resume).toBe(state.resume);
  expect(editor.openSectionId).toBe("skills");
  const edited = {
    ...state.resume,
    basic: { ...state.resume.basic, name: "Grace" },
  };
  const section = {
    ...createResumeSection("simple_list"),
    id: "skills",
    title: "Skills",
  };
  const update = () => edited;
  editor.updateContent(update);
  editor.toggleSection("basic");
  editor.addSection(section);
  editor.removeSection("skills");
  expect(commands.updateContent).toHaveBeenCalledExactlyOnceWith(update);
  expect(commands.toggleSection).toHaveBeenCalledExactlyOnceWith("basic");
  expect(commands.addSection).toHaveBeenCalledExactlyOnceWith(section);
  expect(commands.removeSection).toHaveBeenCalledExactlyOnceWith("skills");
  const preview = mocks.preview.mock.lastCall![0];
  expect(preview.resume).toBe(state.previewResume);
  expect(preview.variant).toBe("resume");
  if (preview.variant === "resume")
    expect(preview.typography).toBe(state.previewTypography);
  expect(preview.measurementKey).toBe(state.document.measurementKey);
  preview.onPaginationReadyChange?.(true);
  expect(commands.onPreviewReadyChange).toHaveBeenCalledExactlyOnceWith(true);
  state.hasVersionLoadError = true;
  view.rerender(<ResumeDetailWorkspaceView {...props} />);
  expect(mocks.editor.mock.lastCall?.[0].hasLoadError).toBe(true);
  expect(view.getByText("Ready preview")).toBeTruthy();
  state.hasLoadError = true;
  view.rerender(<ResumeDetailWorkspaceView {...props} />);
  expect(view.queryByText("Ready preview")).toBeNull();
  fireEvent.click(view.getByRole("button", { name: messages.retry }));
  expect(commands.retryLoad).toHaveBeenCalledOnce();
});
