import { Outlet, useLocation } from "react-router-dom";

import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import {
  getWorkspaceRoute,
  getWorkspaceViewFromRoute,
} from "@/lib/workspace-route";

export function WorkspaceLateralLayout({ onLogout }: { onLogout: () => void }) {
  const { pathname } = useLocation();
  const activeView = getWorkspaceViewFromRoute(getWorkspaceRoute(pathname));

  return (
    <WorkspaceShell activeView={activeView} onLogout={onLogout}>
      <Outlet />
    </WorkspaceShell>
  );
}
