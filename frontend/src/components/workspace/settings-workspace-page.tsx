import { SettingsPanel } from "@/components/settings-panel";
import { SettingsPanelSkeleton } from "@/components/settings-panel-skeleton";
import { useWorkspacePreferencesRoute } from "@/components/workspace/use-workspace-preferences-route";
import { useRememberWorkspaceLateralRouteData } from "@/components/workspace/use-workspace-lateral-route-data";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

export function SettingsWorkspacePage({
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
    kind: "settings",
    locale,
    messages,
    onLocaleChange,
    persistence,
  });
  useRememberWorkspaceLateralRouteData(
    "settings",
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

  if (!preferences.hasLoaded) {
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
