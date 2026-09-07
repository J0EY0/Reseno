import {
  Bot,
  FolderOpen,
  LayoutTemplate,
  Settings2,
  Trash2,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import type { AppMessages } from "@/i18n";
import { getWorkspacePath } from "@/lib/workspace-route";
import type { WorkspaceView } from "@/types/resume";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
} from "@/components/ui/sidebar-layout";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar-menu";
import { useSidebar } from "@/components/ui/sidebar";

const navigationIcons: Record<WorkspaceView, typeof FolderOpen> = {
  resume: FolderOpen,
  templates: LayoutTemplate,
  trash: Trash2,
  models: Bot,
  settings: Settings2,
};

export function AppSidebar({
  t,
  activeView,
  pendingView,
  onViewChange,
  onViewPreload,
}: {
  t: AppMessages;
  activeView: WorkspaceView;
  pendingView: WorkspaceView | null;
  onViewChange: (view: WorkspaceView) => void;
  onViewPreload?: (view: WorkspaceView) => void;
}) {
  const { setOpenMobile } = useSidebar();

  const items: Array<{ id: WorkspaceView; label: string }> = [
    { id: "resume", label: t.myResume },
    { id: "templates", label: t.resumeTemplates },
    { id: "trash", label: t.recycleBin },
    { id: "models", label: t.modelSettings },
    { id: "settings", label: t.settings },
  ];

  return (
    <Sidebar
      collapsible="icon"
      className="print:hidden"
    >
      <SidebarHeader className="min-h-20 justify-center overflow-hidden border-sidebar-border px-2 py-3 transition-[min-height] [transition-duration:var(--duration-move)] [transition-timing-function:var(--ease-move)] group-data-[collapsible=icon]:min-h-16">
        <div className="flex h-10 w-full items-center gap-3 overflow-hidden transition-[height] [transition-duration:var(--duration-move)] [transition-timing-function:var(--ease-move)] group-data-[collapsible=icon]:h-8">
          <div className="flex size-10 shrink-0 items-center justify-center transition-[width,height] [transition-duration:var(--duration-move)] [transition-timing-function:var(--ease-move)] group-data-[collapsible=icon]:size-8">
            <img
              src="/logo.svg"
              alt="Reseno"
              className="size-full object-contain"
            />
          </div>
          <div className="min-w-0 transition-[opacity,visibility] [transition-duration:var(--duration-move)] [transition-timing-function:var(--ease-move)] group-data-[collapsible=icon]:invisible group-data-[collapsible=icon]:opacity-0">
            <p className="truncate text-xl leading-tight font-semibold tracking-tight">
              {t.brandTitle}
            </p>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>{t.workspaceTitle}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => {
                const Icon = navigationIcons[item.id];
                const isPending = pendingView === item.id;

                return (
                  <SidebarMenuItem key={item.id}>
                    <SidebarMenuButton
                      asChild
                      isActive={activeView === item.id}
                      onFocus={() => onViewPreload?.(item.id)}
                      onPointerEnter={() => onViewPreload?.(item.id)}
                      tooltip={item.label}
                    >
                      <NavLink
                        to={getWorkspacePath(item.id)}
                        aria-current={activeView === item.id ? "page" : undefined}
                        aria-busy={isPending || undefined}
                        onClick={(event) => {
                          setOpenMobile(false);

                          // Preserve native modified-click behavior while routing
                          // same-tab navigation through the unsaved-change guard.
                          if (
                            event.button !== 0 ||
                            event.metaKey ||
                            event.ctrlKey ||
                            event.shiftKey ||
                            event.altKey
                          ) {
                            return;
                          }

                          event.preventDefault();
                          onViewChange(item.id);
                        }}
                      >
                        <Icon />
                        <span className="transition-opacity [transition-duration:var(--duration-move)] [transition-timing-function:var(--ease-move)] group-data-[collapsible=icon]:opacity-0">
                          {item.label}
                        </span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </Sidebar>
  );
}
