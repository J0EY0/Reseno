import { ResumeGallery } from "@/components/resume-gallery";
import { GalleryRouteSkeleton } from "@/components/workspace-skeletons";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { useResumeGalleryWorkspace } from "@/components/workspace/use-resume-gallery-workspace";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function ResumeGalleryWorkspacePage({
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
  const gallery = useResumeGalleryWorkspace({
    locale,
    messages,
    onLocaleChange,
    persistence,
  });
  useRememberWorkspaceLateralRouteData(
    "resume",
    gallery.hasLoaded ? gallery.routeData : null,
  );

  return (
    <WorkspaceShell
      activeView="resume"
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
          itemCount={Math.max(1, gallery.resumes.length)}
        />
      ) : (
        <div className="flex-1 p-4">
          <ResumeGallery
            locale={locale}
            t={messages}
            resumes={gallery.resumes}
            templates={gallery.templateCatalog}
            isImporting={gallery.isImporting}
            isCreating={gallery.isCreating}
            onOpenResume={(resumeId) => void gallery.openResume(resumeId)}
            onCreateResume={() => void gallery.createResume()}
            onImportResume={(file) => void gallery.importResume(file)}
            onDeleteResume={(resumeId) =>
              void gallery.moveResumesToTrash([resumeId])
            }
            onBulkDeleteResumes={(ids) =>
              void gallery.moveResumesToTrash(ids)
            }
          />
        </div>
      )}
    </WorkspaceShell>
  );
}
