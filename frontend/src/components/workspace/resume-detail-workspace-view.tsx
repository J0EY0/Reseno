import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";

import { AppToaster } from "@/components/app-toaster";
import { ResumeEditorPane } from "@/components/editor/resume-editor-pane";
import type { DocumentCanvasHandle } from "@/components/preview/document-canvas";
import { loadDocumentCanvas } from "@/components/preview/document-canvas-loader";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import {
  ResumeDetailAgentHost,
  ResumeDetailAgentToggle,
} from "@/components/workspace/resume-detail-agent-host";
import { ResumeDetailWorkspaceHeader } from "@/components/workspace/resume-detail-workspace-header";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { WorkspacePreviewSkeleton } from "@/components/workspace-skeletons";
import type { AppMessages, Locale } from "@/i18n";
import { useLocalizedMessages } from "@/i18n/use-localized-messages";
import { cn } from "@/lib/utils";

// Pagination and PDF-ready preview code are owned by the document surface,
// rather than the route shell that must render immediately.
const DocumentCanvas = lazy(loadDocumentCanvas);
const ResumeDetailLeaveDialog = lazy(() =>
  import("@/components/workspace/resume-detail-leave-dialog").then((module) => ({
    default: module.ResumeDetailLeaveDialog,
  })),
);
const ResumeDetailTitleDialog = lazy(() =>
  import("@/components/workspace/resume-detail-title-dialog").then((module) => ({
    default: module.ResumeDetailTitleDialog,
  })),
);

function ResumeDetailContent({
  messages,
  model,
  previewRef,
}: {
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  previewRef: RefObject<DocumentCanvasHandle | null>;
}) {
  const { commands, state } = model;
  const documentMessages = useLocalizedMessages(
    state.resumeItem?.documentLocale ?? null,
  );
  const showDocumentSkeleton = state.showSkeleton || !documentMessages;
  const shouldDockAgent = !state.agent.isPanelCollapsed;
  const workspaceStyle = {
    "--agent-panel-width": "360px",
    "--document-sticky-bottom-gap": "0px",
    "--document-workspace-gutter": "0px",
    "--resume-workspace-columns": shouldDockAgent
      ? "clamp(372px,calc(27vw + 32px),432px) minmax(0,1fr) var(--agent-panel-width)"
      : "clamp(372px,calc(27vw + 32px),432px) minmax(0,1fr) 0px",
  } as CSSProperties;

  return (
    <div
      style={workspaceStyle}
      data-agent-expanded={shouldDockAgent}
      className={cn(
        "workspace-document-enter resume-workspace relative grid min-w-0 flex-1 gap-y-4 gap-x-3 p-4",
        "print:block print:h-auto print:overflow-visible print:p-0",
      )}
    >
      <ResumeEditorPane
        t={messages}
        documentT={documentMessages}
        disabled={Boolean(state.agent.review?.resolvingStatus)}
        resume={state.resume}
        setResume={commands.setResume}
        collapsedState={state.collapsedState}
        setCollapsedState={commands.setCollapsedState}
        hasLoadError={state.hasVersionLoadError}
        showSkeleton={showDocumentSkeleton}
      />

      {showDocumentSkeleton ? (
        <WorkspacePreviewSkeleton />
      ) : (
        <Suspense fallback={<WorkspacePreviewSkeleton />}>
          <DocumentCanvas
            ref={previewRef}
            variant="resume"
            t={messages}
            documentT={documentMessages}
            resume={state.previewResume}
            typography={state.typography}
            template={state.activeTemplate}
            diffs={state.previewDiffs}
            draftReview={
              state.previewReview
                ? {
                    onSelectReviewItem: state.previewReview.selectItem,
                    exitingReviewItemIds:
                      state.previewReview.exitingReviewItemIds,
                    reviewItemIdByOperationId:
                      state.previewReview.reviewItemIdByOperationId,
                    selectedReviewItemId:
                      state.previewReview.selectedItemId ?? undefined,
                  }
                : undefined
            }
            onPaginationReadyChange={commands.onPreviewReadyChange}
            toolbarTrailing={
              <ResumeDetailAgentToggle messages={messages} model={model} />
            }
          />
        </Suspense>
      )}

      <ResumeDetailAgentHost
        messages={messages}
        model={model}
      />
    </div>
  );
}

export function ResumeDetailWorkspaceView({
  locale,
  messages,
  model,
  onLocaleChange,
  previewRef,
}: {
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  onLocaleChange: (locale: Locale) => void;
  previewRef: RefObject<DocumentCanvasHandle | null>;
}) {
  const headerRef = useRef<HTMLElement | null>(null);
  const [documentStickyTop, setDocumentStickyTop] = useState(64);

  useEffect(() => {
    const headerElement = headerRef.current;
    if (!headerElement) {
      return;
    }

    const syncDocumentStickyTop = () => {
      const nextStickyTop = Math.ceil(
        headerElement.getBoundingClientRect().height,
      );
      setDocumentStickyTop((current) =>
        current === nextStickyTop ? current : nextStickyTop,
      );
    };

    syncDocumentStickyTop();
    const resizeObserver = new ResizeObserver(syncDocumentStickyTop);
    resizeObserver.observe(headerElement);
    window.addEventListener("resize", syncDocumentStickyTop);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener("resize", syncDocumentStickyTop);
    };
  }, []);

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="fixed left-4 top-4 z-50 -translate-y-20 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground shadow-md transition-transform focus-visible:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 print:hidden"
      >
        {messages.skipToContent}
      </a>
      <AppToaster theme={model.state.theme} position="bottom-right" />
      <Suspense fallback={null}>
        <ResumeDetailTitleDialog messages={messages} model={model} />
        <ResumeDetailLeaveDialog messages={messages} model={model} />
      </Suspense>
      <SidebarInset
        id="main-content"
        tabIndex={-1}
        className="app-shell app-shell--document"
        style={
          {
            "--document-sticky-top": `${documentStickyTop}px`,
          } as CSSProperties
        }
      >
        <ResumeDetailWorkspaceHeader
          headerRef={headerRef}
          locale={locale}
          messages={messages}
          model={model}
          onLocaleChange={onLocaleChange}
        />

        {model.state.hasLoadError ? (
          <WorkspaceRouteError
            messages={messages}
            onRetry={model.commands.retryLoad}
          />
        ) : (
          <ResumeDetailContent
            messages={messages}
            model={model}
            previewRef={previewRef}
          />
        )}
      </SidebarInset>
    </SidebarProvider>
  );
}
