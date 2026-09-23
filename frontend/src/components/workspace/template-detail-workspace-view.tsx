import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import { AppToaster } from "@/components/app-toaster";
import { ResourceErrorBoundary } from "@/components/resource-error-boundary";
import { loadDocumentCanvas } from "@/components/preview/document-canvas-loader";
import { TemplateEditor } from "@/components/templates/template-editor";
import { TemplatePreviewToolbar } from "@/components/templates/template-preview-toolbar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { Spinner } from "@/components/ui/spinner";
import { TemplateDetailWorkspaceHeader } from "@/components/workspace/template-detail-workspace-header";
import { TemplateWorkspaceColumns } from "@/components/workspace/template-workspace-columns";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import {
  WorkspacePanelSkeleton,
  WorkspacePreviewSkeleton,
} from "@/components/workspace-skeletons";
import type { TemplateDetailWorkspaceController } from "@/components/workspace/use-template-detail-workspace";
import type { AppMessages, Locale } from "@/i18n";

const DocumentCanvas = lazy(loadDocumentCanvas);
const TemplateDetailLeaveDialog = lazy(() =>
  import("@/components/workspace/template-detail-leave-dialog").then(
    (module) => ({
      default: module.TemplateDetailLeaveDialog,
    }),
  ),
);

function TemplateDetailContent({
  controller,
  locale,
  messages,
}: {
  controller: TemplateDetailWorkspaceController;
  locale: Locale;
  messages: AppMessages;
}) {
  const { template, templatePreviewMessages, templatePreviewResume } =
    controller;
  const previewLoading = (
    <div className="grid min-h-0 flex-1 place-items-center">
      <Spinner aria-label={messages.loading} />
    </div>
  );

  return (
    <TemplateWorkspaceColumns
      locale={locale}
      editor={
        <section className="resume-editor-panel resume-template-editor-panel flex flex-col gap-4 print:hidden">
          {controller.hasLoaded && template ? (
            <TemplateEditor
              t={messages}
              locale={locale}
              template={template}
              defaultTemplateId={controller.defaultTemplateId}
              isCreating={controller.isCreating}
              settingDefaultTemplateId={controller.settingDefaultTemplateId}
              onCreateCustomTemplate={() =>
                void controller.createCustomTemplate()
              }
              onSetDefaultTemplate={(templateId) =>
                void controller.setDefaultTemplate(templateId)
              }
              onUpdateTemplate={controller.updateTemplate}
            />
          ) : (
            <div data-slot="template-editor-skeleton" className="min-h-[520px]">
              <WorkspacePanelSkeleton />
            </div>
          )}
        </section>
      }
    >
      {controller.hasLoaded && template ? (
        <section className="resume-preview-card relative flex min-h-0 min-w-0 flex-col overflow-hidden rounded-(--radius-preview) border bg-card">
          <TemplatePreviewToolbar
            messages={messages}
            templateLocale={controller.templateLocale}
            disabled={controller.settingDefaultTemplateId !== null}
            onTemplateLocaleChange={controller.setTemplateLocale}
          />
          {templatePreviewMessages && templatePreviewResume ? (
            <ResourceErrorBoundary className="m-4 mt-14">
              <Suspense fallback={previewLoading}>
                <DocumentCanvas
                  variant="template"
                  className="relative isolate flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
                  t={messages}
                  documentT={templatePreviewMessages}
                  resume={templatePreviewResume}
                  template={template}
                  onChangeTemplateImage={controller.updateTemplateImage}
                />
              </Suspense>
            </ResourceErrorBoundary>
          ) : (
            previewLoading
          )}
        </section>
      ) : (
        <WorkspacePreviewSkeleton />
      )}
    </TemplateWorkspaceColumns>
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
      <AppToaster theme={controller.theme} position="bottom-right" />
      <Suspense fallback={null}>
        <TemplateDetailLeaveDialog
          changeCount={controller.saveChangeCount}
          isOpen={controller.leave.isOpen}
          isResolving={controller.leave.isResolving}
          messages={messages}
          onCancel={controller.leave.cancelLeave}
          onDiscard={controller.leave.discardAndLeave}
          onSave={controller.leave.saveAndLeave}
        />
      </Suspense>
      <SidebarInset
        id="main-content"
        tabIndex={-1}
        className="app-shell app-shell--document"
        style={
          {
            "--document-sticky-bottom-gap": "0px",
            "--document-sticky-top": `${documentStickyTop}px`,
            "--document-workspace-gutter": "0px",
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
          onUpdateTemplate={controller.updateTemplate}
          resolvedTheme={controller.resolvedTheme}
          saveState={controller.saveState}
          template={controller.hasLoaded ? controller.template : null}
        />

        {controller.hasLoadError ? (
          <WorkspaceRouteError
            messages={messages}
            onRetry={controller.retryLoad}
          />
        ) : (
          <TemplateDetailContent
            controller={controller}
            locale={locale}
            messages={messages}
          />
        )}
      </SidebarInset>
    </SidebarProvider>
  );
}
