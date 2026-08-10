import { TemplateGallery } from "@/components/templates/template-gallery";
import { GalleryRouteSkeleton } from "@/components/workspace-skeletons";
import { useTemplateGalleryWorkspace } from "@/components/workspace/use-template-gallery-workspace";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function TemplateGalleryWorkspacePage({
  locale,
  messages,
  onLocaleChange,
  onLogout,
  persistence,
}: {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  persistence: WorkspacePreferencesPersistence;
}) {
  const gallery = useTemplateGalleryWorkspace({
    locale,
    messages,
    onLocaleChange,
    persistence,
  });
  useRememberWorkspaceLateralRouteData(
    "templates",
    gallery.hasLoaded ? gallery.routeData : null,
  );

  return (
    <WorkspaceShell
      activeView="templates"
      locale={locale}
      messages={messages}
      theme={gallery.theme}
      resolvedTheme={gallery.resolvedTheme}
      persistence={persistence}
      onLocaleChange={onLocaleChange}
      onThemeChange={gallery.changeTheme}
      onLogout={onLogout}
    >
      {gallery.hasLoadError ? (
        <WorkspaceRouteError
          messages={messages}
          onRetry={gallery.retryLoad}
        />
      ) : !gallery.hasLoaded ? (
        <GalleryRouteSkeleton
          itemCount={Math.max(1, gallery.templateCatalog.length)}
        />
      ) : (
        <div className="flex-1 p-4">
          <TemplateGallery
            t={messages}
            previewResume={gallery.previewResume}
            templates={gallery.templateCatalog}
            defaultTemplateId={gallery.defaultTemplateId}
            isImporting={gallery.isImporting}
            isCreating={gallery.isCreating}
            settingDefaultTemplateId={gallery.settingDefaultTemplateId}
            onOpenTemplate={(templateId) =>
              void gallery.openTemplate(templateId)
            }
            onSetDefaultTemplate={gallery.setDefaultTemplate}
            onCreateCustomTemplate={() => void gallery.createCustomTemplate()}
            onImportTemplates={(file) => void gallery.importTemplates(file)}
            onDeleteTemplates={(ids) => void gallery.deleteTemplates(ids)}
          />
        </div>
      )}
    </WorkspaceShell>
  );
}
