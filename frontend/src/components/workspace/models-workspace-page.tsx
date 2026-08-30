import { ModelConfigPanel } from "@/components/model-config-panel";
import { ModelConfigPanelSkeleton } from "@/components/workspace-skeletons";
import { useWorkspacePreferencesRoute } from "@/components/workspace/use-workspace-preferences-route";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function ModelsWorkspacePage({
  locale,
  messages,
  onLocaleChange,
  persistence,
}: {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
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

  if (preferences.hasLoadError) {
    return (
      <WorkspaceRouteError
        messages={messages}
        onRetry={preferences.retryLoad}
      />
    );
  }

  return (
    <div className="flex-1 p-4">
      {!preferences.hasLoaded ? (
        <ModelConfigPanelSkeleton />
      ) : (
        <ModelConfigPanel
          locale={locale}
          t={messages}
          configs={preferences.modelConfigs}
          onChange={preferences.changeModelConfigs}
        />
      )}
    </div>
  );
}
