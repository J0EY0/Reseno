import { useState, type CSSProperties } from "react";

import { SettingsPanelSkeleton } from "@/components/settings-panel-skeleton";
import {
  getInitialSidebarOpen,
  SIDEBAR_WIDTH,
  SIDEBAR_WIDTH_ICON,
} from "@/components/ui/sidebar-state";
import { Skeleton } from "@/components/ui/skeleton";
import { GalleryRouteSkeleton } from "@/components/gallery-skeletons";

export function WorkspaceEntrySkeleton({
  destination,
  label,
}: {
  destination: "resume" | "settings";
  label: string;
}) {
  const [sidebarOpen] = useState(() => getInitialSidebarOpen(true));

  return (
    <div
      data-slot="workspace-entry-skeleton"
      data-destination={destination}
      role="status"
      aria-busy="true"
    >
      <span className="sr-only">{label}</span>
      <div
        aria-hidden="true"
        className="flex min-h-svh w-full"
        style={{
          "--sidebar-width": SIDEBAR_WIDTH,
          "--sidebar-width-icon": SIDEBAR_WIDTH_ICON,
        } as CSSProperties}
      >
        <aside
          data-state={sidebarOpen ? "expanded" : "collapsed"}
          className="group hidden w-(--sidebar-width) shrink-0 flex-col border-r border-sidebar-border bg-sidebar data-[state=collapsed]:w-(--sidebar-width-icon) md:flex"
        >
          <div className="flex min-h-20 flex-col justify-center px-2 py-3 group-data-[state=collapsed]:min-h-16">
            <div className="flex items-center gap-3 overflow-hidden">
              <Skeleton className="size-10 shrink-0 rounded-2xl group-data-[state=collapsed]:size-8" />
              <div className="grid gap-2 group-data-[state=collapsed]:hidden">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-3 w-36" />
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-1 p-2">
            <div className="flex h-8 items-center px-2 group-data-[state=collapsed]:hidden">
              <Skeleton className="h-3 w-16" />
            </div>
            {Array.from({ length: 5 }, (_, index) => (
              <div key={index} className="flex h-8 items-center gap-2 px-2">
                <Skeleton className="size-4 shrink-0" />
                <Skeleton className="h-4 w-24 group-data-[state=collapsed]:hidden" />
              </div>
            ))}
          </div>
        </aside>
        <main data-slot="sidebar-inset" className="app-shell relative flex min-w-0 flex-1 flex-col bg-background">
          <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-border px-4">
            <div className="flex items-center gap-4">
              <Skeleton className="size-7" />
              <Skeleton className="h-4 w-24" />
            </div>
            <Skeleton className="size-9 md:w-20" />
          </header>
          {destination === "settings" ? (
            <SettingsPanelSkeleton />
          ) : (
            <GalleryRouteSkeleton itemCount={1} />
          )}
        </main>
      </div>
    </div>
  );
}
