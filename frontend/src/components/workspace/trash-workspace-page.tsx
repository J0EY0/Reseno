import { RecycleBinPanel } from "@/components/recycle-bin-panel";
import { WorkspaceRouteSkeleton } from "@/components/workspace-skeletons";
import { useTrashWorkspace } from "@/components/workspace/use-trash-workspace";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function TrashWorkspacePage({
  locale,
  messages,
  persistence,
}: {
  locale: Locale;
  messages: AppMessages;
  persistence: WorkspacePreferencesPersistence;
}) {
  const trash = useTrashWorkspace({
    locale,
    messages,
    persistence,
  });
  useRememberWorkspaceLateralRouteData(
    "trash",
    trash.hasLoaded ? trash.routeData : null,
  );

  if (trash.hasLoadError) {
    return <WorkspaceRouteError messages={messages} onRetry={trash.retryLoad} />;
  }

  if (!trash.hasLoaded) {
    return <WorkspaceRouteSkeleton />;
  }

  return (
    <RecycleBinPanel
      locale={locale}
      t={messages}
      deletedResumes={trash.deletedResumes}
      deletedTemplates={trash.deletedTemplates}
      templates={trash.templates}
      templatePreviewResume={trash.templatePreviewResume}
      onRestoreResume={trash.restoreResumes}
      onDeleteResumeForever={trash.permanentlyDeleteResumes}
      onRestoreTemplate={trash.restoreTemplates}
      onDeleteTemplateForever={trash.permanentlyDeleteTemplates}
    />
  );
}
