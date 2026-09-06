import { ModelConfigPanel } from "@/components/model-config-panel";
import { ModelConfigPanelSkeleton } from "@/components/workspace-skeletons";
import { useWorkspacePreferencesRoute } from "@/components/workspace/use-workspace-preferences-route";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";

export function ModelsWorkspacePage() {
  const { locale, messages } = useWorkspacePreferences();
  const preferences = useWorkspacePreferencesRoute({
    kind: "models",
    locale,
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
