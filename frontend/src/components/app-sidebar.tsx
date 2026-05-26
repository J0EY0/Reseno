import {
  Bot,
  FolderOpen,
  LayoutTemplate,
  Settings2,
  Trash2,
} from "lucide-react";

import type { AppMessages } from "@/i18n";
import type { WorkspaceView } from "@/types/resume";

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { useSidebar } from "@/components/ui/sidebar-context";

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
  onViewChange,
  onViewPreload,
}: {
  t: AppMessages;
  activeView: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
  onViewPreload?: (view: WorkspaceView) => void;
}) {
  const { open, setOpenMobile } = useSidebar();

  const items: Array<{ id: WorkspaceView; label: string }> = [
    { id: "resume", label: t.myResume },
    { id: "templates", label: t.resumeTemplates },
    { id: "trash", label: t.recycleBin },
    { id: "models", label: t.modelSettings },
    { id: "settings", label: t.settings },
  ];

  return (
    <Sidebar className="print:hidden" style={{ viewTransitionName: "persistent-sidebar" }}>
      <SidebarHeader className="min-h-20 justify-center  border-sidebar-border px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-2xl">
            <img
              src="/logo.svg"
              alt="ResuMate"
              className="size-[170%] max-w-none object-cover"
            />
          </div>
          {open ? (
            <div className="min-w-0">
              <p className="truncate text-base font-semibold tracking-tight">
                {t.brandTitle}
              </p>
              <p className="truncate text-sm text-sidebar-foreground/65">
                {t.brandSubtitle}
              </p>
            </div>
          ) : null}
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>{t.workspaceTitle}</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => {
                const Icon = navigationIcons[item.id];

                return (
                  <SidebarMenuItem key={item.id}>
                    <SidebarMenuButton
                      isActive={activeView === item.id}
                      onFocus={() => onViewPreload?.(item.id)}
                      onPointerEnter={() => onViewPreload?.(item.id)}
                      onClick={() => {
                        onViewChange(item.id);
                        setOpenMobile(false);
                      }}
                      title={item.label}
                    >
                      <Icon className="size-4 shrink-0" />
                      {open ? <span>{item.label}</span> : null}
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
