import { RecycleBinPanel } from "@/components/recycle-bin-panel";
import { WorkspaceRouteSkeleton } from "@/components/workspace-skeletons";
import { useTrashWorkspace } from "@/components/workspace/use-trash-workspace";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function TrashWorkspacePage({
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
  const trash = useTrashWorkspace({
    locale,
    messages,
    onLocaleChange,
    persistence,
  });

  return (
    <WorkspaceShell
      activeView="trash"
      locale={locale}
      messages={messages}
      theme={trash.theme}
      resolvedTheme={trash.resolvedTheme}
      onLocaleChange={onLocaleChange}
      onThemeChange={trash.changeTheme}
      onLogout={onLogout}
    >
      {trash.hasLoadError ? (
        <WorkspaceRouteError
          messages={messages}
          onRetry={trash.retryLoad}
        />
      ) : !trash.hasLoaded ? (
        <WorkspaceRouteSkeleton />
      ) : (
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
      )}
    </WorkspaceShell>
  );
}
