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
import type { DocumentPreviewHandle } from "@/components/preview/document-preview-card";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { ViewTransitionBoundary } from "@/components/view-transition";
import { ResumeDetailAgentHost } from "@/components/workspace/resume-detail-agent-host";
import { ResumeDetailLeaveDialog } from "@/components/workspace/resume-detail-leave-dialog";
import { ResumeDetailTitleDialog } from "@/components/workspace/resume-detail-title-dialog";
import { ResumeDetailWorkspaceHeader } from "@/components/workspace/resume-detail-workspace-header";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { WorkspacePreviewSkeleton } from "@/components/workspace-skeletons";
import type { AppMessages, Locale } from "@/i18n";
import { cn } from "@/lib/utils";

// Pagination and PDF-ready preview code are owned by the document surface,
// rather than the route shell that must render immediately.
const DocumentPreviewCard = lazy(() =>
  import("@/components/preview/document-preview-card").then((module) => ({
    default: module.DocumentPreviewCard,
  })),
);

function ResumeDetailContent({
  locale,
  messages,
  model,
  previewRef,
}: {
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  previewRef: RefObject<DocumentPreviewHandle | null>;
}) {
  const { commands, state } = model;
  const shouldDockAgent = !state.agent.isPanelCollapsed;
  const workspaceStyle = {
    "--resume-workspace-columns": shouldDockAgent
      ? "clamp(340px,27vw,400px) minmax(0,1fr) 18px clamp(320px,25vw,360px)"
      : "clamp(340px,27vw,400px) minmax(0,1fr) 18px 0px",
  } as CSSProperties;

  return (
    <div
      style={workspaceStyle}
      data-agent-expanded={shouldDockAgent}
      className={cn(
        "resume-workspace relative grid min-w-0 flex-1 gap-y-4 gap-x-3 p-4 xl:gap-x-2",
        "print:block print:h-auto print:overflow-visible print:p-0",
      )}
    >
      <ResumeEditorPane
        t={messages}
        resume={state.resume}
        setResume={commands.setResume}
        collapsedState={state.collapsedState}
        setCollapsedState={commands.setCollapsedState}
        hasLoadError={state.hasVersionLoadError}
        showSkeleton={state.showSkeleton}
      />

      {state.showSkeleton ? (
        <WorkspacePreviewSkeleton />
      ) : (
        <Suspense fallback={<WorkspacePreviewSkeleton />}>
          <DocumentPreviewCard
            ref={previewRef}
            variant="resume"
            id={state.resumeItem?.id ?? "resume"}
            t={messages}
            resume={state.previewResume}
            typography={state.typography}
            template={state.activeTemplate}
            diffs={state.agent.draft?.diffs}
            onPaginationReadyChange={commands.onPreviewReadyChange}
          />
        </Suspense>
      )}

      <ResumeDetailAgentHost
        locale={locale}
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
  previewRef: RefObject<DocumentPreviewHandle | null>;
}) {
  const headerRef = useRef<HTMLElement | null>(null);
  const [documentStickyTop, setDocumentStickyTop] = useState(96);

  useEffect(() => {
    const headerElement = headerRef.current;
    if (!headerElement) {
      return;
    }

    const syncDocumentStickyTop = () => {
      const nextStickyTop = Math.ceil(
        headerElement.getBoundingClientRect().height + 16,
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
      <ResumeDetailTitleDialog messages={messages} model={model} />
      <ResumeDetailLeaveDialog messages={messages} model={model} />
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

        <ViewTransitionBoundary
          default="none"
          enter={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            default: "none",
          }}
          exit={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            default: "none",
          }}
          update={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            default: "none",
          }}
        >
          {model.state.hasLoadError ? (
            <WorkspaceRouteError
              messages={messages}
              onRetry={model.commands.retryLoad}
            />
          ) : (
            <ResumeDetailContent
              locale={locale}
              messages={messages}
              model={model}
              previewRef={previewRef}
            />
          )}
        </ViewTransitionBoundary>
      </SidebarInset>
    </SidebarProvider>
  );
}
