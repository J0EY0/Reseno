import { Ellipsis, Languages, LogOut, Moon, Sun } from "lucide-react";
import {
  lazy,
  startTransition,
  Suspense,
  useState,
  type ReactNode,
} from "react";
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
import {
  prepareWorkspaceRoute,
  WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
} from "@/components/workspace/workspace-route-preparation";
import { preloadWorkspaceRoute } from "@/components/workspace/workspace-route-loaders";
import { useWorkspacePreferences } from "@/components/workspace/workspace-preferences-context";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { AppMessages } from "@/i18n";
import { isAbortError } from "@/lib/api-client";
import {
  createWorkspaceLateralRouteHandoff,
  deleteWorkspaceLateralRouteHandoff,
} from "@/lib/workspace-route-memory";
import { getWorkspacePath } from "@/lib/workspace-route";
import type { WorkspaceView } from "@/types/resume";

const WorkspaceMobileActionsMenu = lazy(() =>
  import("@/components/workspace/workspace-mobile-actions-menu").then(
    ({ WorkspaceMobileActionsMenu: Component }) => ({ default: Component }),
  ),
);
const MOBILE_HEADER_MEDIA_QUERY = "(max-width: 767px)";

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
  onLogout,
}: {
  activeView: WorkspaceView;
  children: ReactNode;
  onLogout: () => void;
}) {
  const navigate = useNavigate();
  const { beginNavigation } = useWorkspaceNavigationTransaction();
  const {
    changeTheme,
    changeLocale: onLocaleChange,
    locale,
    messages,
    persistence,
    resolvedTheme,
    theme,
  } = useWorkspacePreferences();
  const isMobile = useMediaQuery(MOBILE_HEADER_MEDIA_QUERY);
  const [pendingView, setPendingView] = useState<WorkspaceView | null>(null);
  const pageTitle = getWorkspacePageTitle(activeView, messages);

  function handleViewPreload(view: WorkspaceView) {
    void preloadWorkspaceRoute(view).catch(() => undefined);
  }

  async function handleViewChange(view: WorkspaceView) {
    const intent = beginNavigation();
    const clearPendingView = () => {
      setPendingView((current) => (current === view ? null : current));
    };
    intent.signal.addEventListener("abort", clearPendingView, { once: true });
    if (view === activeView) {
      clearPendingView();
      intent.finish();
      return;
    }

    setPendingView(view);
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
      clearPendingView();
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
      clearPendingView();
      intent.finish();
      startTransition(() => {
        navigate(path, { state });
      });
    } catch (error) {
      if (handoffToken) {
        deleteWorkspaceLateralRouteHandoff(handoffToken);
      }
      clearPendingView();
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
        pendingView={pendingView}
        onViewChange={handleViewChange}
        onViewPreload={handleViewPreload}
      />

      <SidebarInset id="main-content" tabIndex={-1} className="app-shell">
        <header
          className="sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border bg-background px-4 print:hidden"
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
            <h1 className="truncate text-sm font-medium text-foreground">
              {pageTitle}
            </h1>
          </div>

          <div className="hidden flex-wrap items-center justify-end gap-2 md:flex">
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
                    changeTheme(
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

          {isMobile ? (
            <Suspense
              fallback={
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  aria-label={messages.actions}
                  title={messages.actions}
                  disabled
                >
                  <Ellipsis />
                </Button>
              }
            >
              <WorkspaceMobileActionsMenu
                locale={locale}
                messages={messages}
                onLocaleChange={onLocaleChange}
                onLogout={handleLogout}
                onThemeChange={changeTheme}
                resolvedTheme={resolvedTheme}
              />
            </Suspense>
          ) : null}
        </header>

        <div
          key={activeView}
          data-workspace-view={activeView}
          className="workspace-route-stage flex min-h-0 flex-1 flex-col"
          aria-busy={pendingView !== null}
        >
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
