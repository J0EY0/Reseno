import { useLayoutEffect } from "react";

import { SettingsPanel } from "@/components/settings-panel";
import { SettingsPanelSkeleton } from "@/components/settings-panel-skeleton";
import { useWorkspacePreferencesRoute } from "@/components/workspace/use-workspace-preferences-route";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";

export function SettingsWorkspacePage({ onLogout, onReady }: {
  onLogout: () => void;
  onReady?: () => void;
}) {
  const { locale, messages } = useWorkspacePreferences();
  const preferences = useWorkspacePreferencesRoute({
    kind: "settings",
    locale,
  });
  useRememberWorkspaceLateralRouteData(
    "settings",
    preferences.hasLoaded ? preferences.routeData : null,
  );

  useLayoutEffect(() => {
    if (preferences.hasLoaded || preferences.hasLoadError) onReady?.();
  }, [onReady, preferences.hasLoadError, preferences.hasLoaded]);

  if (preferences.hasLoadError) {
    return (
      <WorkspaceRouteError
        messages={messages}
        onRetry={preferences.retryLoad}
      />
    );
  }

  if (!preferences.hasLoaded || !preferences.agentSettings) {
    return <SettingsPanelSkeleton />;
  }

  return (
    <SettingsPanel
      locale={locale}
      t={messages}
      theme={preferences.theme}
      onThemeChange={preferences.changeTheme}
      onLocaleChange={preferences.changeLocale}
      agentSettings={preferences.agentSettings}
      onAgentSettingsChange={preferences.changeAgentSettings}
      modelConfigs={preferences.modelConfigs}
      onPasswordChanged={onLogout}
    />
  );
}
