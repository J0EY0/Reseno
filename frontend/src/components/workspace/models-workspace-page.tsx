import { ModelConfigPanel } from "@/components/model-config-panel";
import { WorkspaceContentSkeleton } from "@/components/workspace-skeletons";
import { useWorkspacePreferencesRoute } from "@/components/workspace/use-workspace-preferences-route";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function ModelsWorkspacePage({
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
  const preferences = useWorkspacePreferencesRoute({
    kind: "models",
    locale,
    messages,
    onLocaleChange,
    persistence,
  });
  useRememberWorkspaceLateralRouteData(
    "models",
    preferences.hasLoaded ? preferences.routeData : null,
  );

  return (
    <WorkspaceShell
      activeView="models"
      locale={locale}
      messages={messages}
      theme={preferences.theme}
      resolvedTheme={preferences.resolvedTheme}
      persistence={persistence}
      onLocaleChange={onLocaleChange}
      onThemeChange={preferences.changeTheme}
      onLogout={onLogout}
    >
      {preferences.hasLoadError ? (
        <WorkspaceRouteError
          messages={messages}
          onRetry={preferences.retryLoad}
        />
      ) : !preferences.hasLoaded ? (
        <div className="flex-1 p-4">
          <WorkspaceContentSkeleton />
        </div>
      ) : (
        <div className="flex-1 p-4">
          <ModelConfigPanel
            locale={locale}
            t={messages}
            configs={preferences.modelConfigs}
            onChange={preferences.changeModelConfigs}
          />
        </div>
      )}
    </WorkspaceShell>
  );
}
