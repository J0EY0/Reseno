import { Languages, LogOut, Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

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
import {
  prepareWorkspaceRoute,
  preloadWorkspaceRoute,
  WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
} from "@/components/workspace/workspace-route-preparation";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import type { AppMessages, Locale } from "@/i18n";
import { isAbortError } from "@/lib/api-client";
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
  const { beginNavigation } = useWorkspaceNavigationTransaction();
  const pageTitle = getWorkspacePageTitle(activeView, messages);

  function handleViewPreload(view: WorkspaceView) {
    void preloadWorkspaceRoute(view).catch(() => undefined);
  }

  async function handleViewChange(view: WorkspaceView) {
    const intent = beginNavigation();
    if (view === activeView) {
      intent.finish();
      return;
    }

    const path = getWorkspacePath(view);
    toast.dismiss(WORKSPACE_NAVIGATION_ERROR_TOAST_ID);
    let prepared;
    try {
      prepared = await prepareWorkspaceRoute(view, persistence, {
        signal: intent.signal,
      });
    } catch (error) {
      if (
        intent.signal.aborted ||
        isAbortError(error) ||
        !intent.isCurrent()
      ) {
        return;
      }
      intent.finish();
      console.error("Failed to prepare the workspace route.", error);
      toast.error(messages.loadError, {
        closeButton: true,
        id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
      });
      return;
    }

    if (!intent.isCurrent()) {
      return;
    }

    let handoffToken: string | null = null;
    try {
      const state = createWorkspaceLateralRouteHandoff(prepared);
      handoffToken = state.token;
      intent.finish();
      navigate(path, { state });
    } catch (error) {
      if (handoffToken) {
        deleteWorkspaceLateralRouteHandoff(handoffToken);
      }
      intent.finish();
      console.error("Failed to prepare the workspace route.", error);
      toast.error(messages.loadError, {
        closeButton: true,
        id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
      });
    }
  }

  function handleLogout() {
    const intent = beginNavigation();
    intent.finish();
    onLogout();
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
            <Button type="button" variant="outline" onClick={handleLogout}>
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
