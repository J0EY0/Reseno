import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { AppSidebar } from "@/components/app-sidebar";
import { AppToaster } from "@/components/app-toaster";
import { TemplateEditor } from "@/components/templates/template-editor";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { ViewTransitionBoundary } from "@/components/view-transition";
import { TemplateDetailLeaveDialog } from "@/components/workspace/template-detail-leave-dialog";
import { TemplateDetailWorkspaceHeader } from "@/components/workspace/template-detail-workspace-header";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import {
  WorkspacePanelSkeleton,
  WorkspacePreviewSkeleton,
} from "@/components/workspace-skeletons";
import type { TemplateDetailWorkspaceController } from "@/components/workspace/use-template-detail-workspace";
import type { AppMessages, Locale } from "@/i18n";

const DocumentPreviewCard = lazy(() =>
  import("@/components/preview/document-preview-card").then((module) => ({
    default: module.DocumentPreviewCard,
  })),
);

function TemplateDetailContent({
  controller,
  messages,
}: {
  controller: TemplateDetailWorkspaceController;
  messages: AppMessages;
}) {
  const template = controller.template;

  return (
    <div className="template-workspace grid min-w-0 flex-1 gap-4 p-4 xl:grid-cols-[460px_minmax(0,1fr)]">
      <section className="resume-editor-panel resume-template-editor-panel flex flex-col gap-4 print:hidden">
        {controller.hasLoaded && template ? (
          <TemplateEditor
            t={messages}
            template={template}
            defaultTemplateId={controller.defaultTemplateId}
            isImporting={false}
            isCreating={controller.isCreating}
            settingDefaultTemplateId={controller.settingDefaultTemplateId}
            onSetDefaultTemplate={(templateId) =>
              void controller.setDefaultTemplate(templateId)
            }
            onCreateCustomTemplate={() =>
              void controller.createCustomTemplate()
            }
            onUpdateTemplate={controller.updateTemplate}
          />
        ) : (
          <WorkspacePanelSkeleton />
        )}
      </section>

      {controller.hasLoaded && template ? (
        <Suspense fallback={<WorkspacePreviewSkeleton />}>
          <DocumentPreviewCard
            variant="template"
            id={template.id}
            t={messages}
            resume={controller.templatePreviewResume}
            template={template}
            onMoveTemplateImage={controller.moveTemplateImage}
          />
        </Suspense>
      ) : (
        <WorkspacePreviewSkeleton />
      )}
    </div>
  );
}

export function TemplateDetailWorkspaceView({
  controller,
  locale,
  messages,
  onLocaleChange,
}: {
  controller: TemplateDetailWorkspaceController;
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
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
      <AppToaster theme={controller.theme} position="bottom-right" />
      <TemplateDetailLeaveDialog
        changeCount={controller.saveChangeCount}
        isOpen={controller.leave.isOpen}
        isResolving={controller.leave.isResolving}
        messages={messages}
        onCancel={controller.leave.cancelLeave}
        onDiscard={controller.leave.discardAndLeave}
        onSave={controller.leave.saveAndLeave}
      />
      <AppSidebar
        t={messages}
        activeView="templates"
        onViewChange={controller.changeView}
        onViewPreload={controller.preloadWorkspaceView}
      />

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
        <TemplateDetailWorkspaceHeader
          changeCount={controller.saveChangeCount}
          headerRef={headerRef}
          lastSavedAt={controller.saveLastSavedAt}
          locale={locale}
          messages={messages}
          onBack={controller.goBack}
          onLocaleChange={onLocaleChange}
          onLogout={controller.logout}
          onSave={controller.save}
          onThemeChange={controller.changeTheme}
          resolvedTheme={controller.resolvedTheme}
          saveState={controller.saveState}
          template={controller.template}
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
          {controller.hasLoadError ? (
            <WorkspaceRouteError
              messages={messages}
              onRetry={controller.retryLoad}
            />
          ) : (
            <TemplateDetailContent
              controller={controller}
              messages={messages}
            />
          )}
        </ViewTransitionBoundary>
      </SidebarInset>
    </SidebarProvider>
  );
}
