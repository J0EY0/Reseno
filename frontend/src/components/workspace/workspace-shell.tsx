import { Languages, LogOut, Moon, Sun } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { AppSidebar } from "@/components/app-sidebar";
import { AppToaster } from "@/components/app-toaster";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { ViewTransitionBoundary } from "@/components/view-transition";
import { prepareWorkspaceRoute } from "@/components/workspace/workspace-route-preparation";
import type { AppMessages, Locale } from "@/i18n";
import {
  createWorkspaceLateralRouteHandoff,
  deleteWorkspaceLateralRouteHandoff,
} from "@/lib/workspace-route-memory";
import { getWorkspacePath } from "@/lib/workspace-route";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type { ThemeMode, WorkspaceView } from "@/types/resume";

function getWorkspacePageTitle(view: WorkspaceView, messages: AppMessages) {
  switch (view) {
    case "templates":
      return messages.resumeTemplates;
    case "trash":
      return messages.recycleBin;
    case "models":
      return messages.modelSettings;
    case "settings":
      return messages.settings;
    case "resume":
    default:
      return messages.myResume;
  }
}

export function WorkspaceShell({
  activeView,
  children,
  locale,
  messages,
  onLocaleChange,
  onLogout,
  onThemeChange,
  persistence,
  resolvedTheme,
  theme,
}: {
  activeView: WorkspaceView;
  children: ReactNode;
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  onThemeChange: (theme: ThemeMode) => void;
  persistence: WorkspacePreferencesPersistence;
  resolvedTheme: "light" | "dark";
  theme: ThemeMode;
}) {
  const navigate = useNavigate();
  const navigationIntentRef = useRef(0);
  const pageTitle = getWorkspacePageTitle(activeView, messages);

  useEffect(
    () => () => {
      navigationIntentRef.current += 1;
    },
    [],
  );

  function handleViewPreload(view: WorkspaceView) {
    void prepareWorkspaceRoute(view, persistence).catch(() => undefined);
  }

  async function handleViewChange(view: WorkspaceView) {
    if (view === activeView) {
      return;
    }

    const intentId = navigationIntentRef.current + 1;
    navigationIntentRef.current = intentId;
    const path = getWorkspacePath(view);
    let handoffToken: string | null = null;
    try {
      const prepared = await prepareWorkspaceRoute(view, persistence);
      if (navigationIntentRef.current !== intentId) {
        return;
      }
      const state = createWorkspaceLateralRouteHandoff(prepared);
      handoffToken = state.token;
      navigate(path, { state });
    } catch {
      if (handoffToken) {
        deleteWorkspaceLateralRouteHandoff(handoffToken);
      }
      if (navigationIntentRef.current !== intentId) {
        return;
      }
      navigate(path);
    }
  }

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="fixed left-4 top-4 z-50 -translate-y-20 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground shadow-md transition-transform focus-visible:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 print:hidden"
      >
        {messages.skipToContent}
      </a>
      <AppToaster theme={theme} position="bottom-right" />
      <AppSidebar
        t={messages}
        activeView={activeView}
        onViewChange={handleViewChange}
        onViewPreload={handleViewPreload}
      />

      <SidebarInset id="main-content" tabIndex={-1} className="app-shell">
        <header
          className="sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-4 print:hidden"
          style={{ viewTransitionName: "persistent-header" }}
        >
          <div className="flex min-w-0 items-center gap-2">
            <SidebarTrigger
              className="-ml-1"
              aria-label={messages.toggleSidebar}
              title={messages.toggleSidebar}
            />
            <Separator
              orientation="vertical"
              className="mr-2 data-[orientation=vertical]:h-4"
            />
            <h1 className="text-sm font-medium text-foreground">
              {pageTitle}
            </h1>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            {activeView !== "settings" ? (
              <>
                <Select
                  value={locale}
                  onValueChange={(value) => {
                    if (value === "zh" || value === "en") {
                      onLocaleChange(value);
                    }
                  }}
                >
                  <SelectTrigger
                    className="w-28 bg-background font-medium transition-all hover:bg-accent hover:text-accent-foreground"
                    aria-label={messages.language}
                  >
                    <Languages className="text-foreground" aria-hidden="true" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent align="end" position="popper" sideOffset={4}>
                    <SelectGroup>
                      <SelectItem value="zh">
                        {messages.languageChinese}
                      </SelectItem>
                      <SelectItem value="en">
                        {messages.languageEnglish}
                      </SelectItem>
                    </SelectGroup>
                  </SelectContent>
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  title={messages.themeToggleLabel}
                  aria-label={messages.themeToggleLabel}
                  onClick={() =>
                    onThemeChange(
                      resolvedTheme === "dark" ? "light" : "dark",
                    )
                  }
                >
                  {resolvedTheme === "dark" ? (
                    <Sun className="size-4" />
                  ) : (
                    <Moon className="size-4" />
                  )}
                </Button>
              </>
            ) : null}
            <Button type="button" variant="outline" onClick={onLogout}>
              <LogOut className="size-4" />
              {messages.logout}
            </Button>
          </div>
        </header>

        <ViewTransitionBoundary
          default="none"
          enter={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            default: "none",
          }}
          exit={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            default: "none",
          }}
          update={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            default: "none",
          }}
        >
          {children}
        </ViewTransitionBoundary>
      </SidebarInset>
    </SidebarProvider>
  );
}
