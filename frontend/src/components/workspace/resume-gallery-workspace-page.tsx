import { useLayoutEffect } from "react";

import { ResumeGallery } from "@/components/resume-gallery";
import { GalleryRouteSkeleton } from "@/components/gallery-skeletons";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { useResumeGalleryWorkspace } from "@/components/workspace/use-resume-gallery-workspace";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";

export function ResumeGalleryWorkspacePage({ onReady }: { onReady?: () => void }) {
  const { locale, messages } = useWorkspacePreferences();
  const gallery = useResumeGalleryWorkspace({
    locale,
    messages,
  });
  useRememberWorkspaceLateralRouteData(
    "resume",
    gallery.hasLoaded ? gallery.routeData : null,
  );

  useLayoutEffect(() => {
    if (gallery.hasLoaded || gallery.hasLoadError) onReady?.();
  }, [gallery.hasLoadError, gallery.hasLoaded, onReady]);

  if (gallery.hasLoadError) {
    return (
      <WorkspaceRouteError messages={messages} onRetry={gallery.retryLoad} />
    );
  }

  if (!gallery.hasLoaded) {
    return (
      <GalleryRouteSkeleton itemCount={Math.max(1, gallery.resumes.length)} />
    );
  }

  return (
    <div className="flex-1 p-4">
      <ResumeGallery
        locale={locale}
        t={messages}
        resumes={gallery.resumes}
        templates={gallery.templateCatalog}
        isImporting={gallery.isImporting}
        isCreating={gallery.isCreating}
        openingResumeId={gallery.openingResumeId}
        onPreloadResumeDetail={gallery.preloadResumeDetail}
        onOpenResume={(resumeId) => void gallery.openResume(resumeId)}
        onCreateResume={(documentLocale) =>
          void gallery.createResume(documentLocale)
        }
        onImportResume={(file) => void gallery.importResume(file)}
        onDeleteResume={(resumeId) =>
          void gallery.moveResumesToTrash([resumeId])
        }
        onBulkDeleteResumes={(ids) =>
          void gallery.moveResumesToTrash(ids)
        }
      />
    </div>
  );
}
