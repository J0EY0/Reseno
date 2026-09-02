import { TemplateGallery } from "@/components/templates/template-gallery";
import { GalleryRouteSkeleton } from "@/components/workspace-skeletons";
import { useTemplateGalleryWorkspace } from "@/components/workspace/use-template-gallery-workspace";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function TemplateGalleryWorkspacePage({
  locale,
  messages,
  persistence,
}: {
  locale: Locale;
  messages: AppMessages;
  persistence: WorkspacePreferencesPersistence;
}) {
  const gallery = useTemplateGalleryWorkspace({
    locale,
    messages,
    persistence,
  });
  useRememberWorkspaceLateralRouteData(
    "templates",
    gallery.hasLoaded ? gallery.routeData : null,
  );

  if (gallery.hasLoadError) {
    return (
      <WorkspaceRouteError messages={messages} onRetry={gallery.retryLoad} />
    );
  }

  if (!gallery.hasLoaded) {
    return (
      <GalleryRouteSkeleton
        itemCount={Math.max(1, gallery.templateCatalog.length)}
      />
    );
  }

  return (
    <div className="flex-1 p-4">
      <TemplateGallery
        t={messages}
        previewMessages={gallery.previewMessages}
        previewResumes={gallery.previewResumes}
        templates={gallery.templateCatalog}
        defaultTemplateId={gallery.defaultTemplateId}
        templateLocale={gallery.templateLocale}
        isImporting={gallery.isImporting}
        isCreating={gallery.isCreating}
        openingTemplateId={gallery.openingTemplateId}
        settingDefaultTemplateId={gallery.settingDefaultTemplateId}
        onPreloadTemplateDetail={gallery.preloadTemplateDetail}
        onOpenTemplate={(templateId) => void gallery.openTemplate(templateId)}
        onSetDefaultTemplate={gallery.setDefaultTemplate}
        onTemplateLocaleChange={gallery.setTemplateLocale}
        onCreateCustomTemplate={() => void gallery.createCustomTemplate()}
        onImportTemplates={(file) => void gallery.importTemplates(file)}
        onDeleteTemplates={(ids) => void gallery.deleteTemplates(ids)}
      />
    </div>
  );
}
