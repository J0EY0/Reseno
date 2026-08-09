import { SettingsPanel } from "@/components/settings-panel";
import { WorkspaceRouteSkeleton } from "@/components/workspace-skeletons";
import { useWorkspacePreferencesRoute } from "@/components/workspace/use-workspace-preferences-route";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
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

  return (
    <WorkspaceShell
      activeView="settings"
      locale={locale}
      messages={messages}
      theme={preferences.theme}
      resolvedTheme={preferences.resolvedTheme}
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
        <WorkspaceRouteSkeleton />
      ) : (
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
      )}
    </WorkspaceShell>
  );
}
