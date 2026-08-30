import { Outlet, useLocation } from "react-router-dom";

import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { WorkspaceThemeProvider } from "@/components/workspace/workspace-theme";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  getWorkspaceRoute,
  getWorkspaceViewFromRoute,
} from "@/lib/workspace-route";

export function WorkspaceLateralLayout({
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
  const { pathname } = useLocation();
  const activeView = getWorkspaceViewFromRoute(getWorkspaceRoute(pathname));

  return (
    <WorkspaceThemeProvider
      locale={locale}
      messages={messages}
      onLocaleChange={onLocaleChange}
      persistence={persistence}
    >
      <WorkspaceShell
        activeView={activeView}
        locale={locale}
        messages={messages}
        onLocaleChange={onLocaleChange}
        onLogout={onLogout}
        persistence={persistence}
      >
        <Outlet />
      </WorkspaceShell>
    </WorkspaceThemeProvider>
  );
}
