import { useLayoutEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import {
  rememberWorkspaceLateralRoute,
  resolveWorkspaceLateralRoute,
  type PreparedWorkspaceRoute,
  type WorkspaceLateralRouteDataMap,
} from "@/lib/workspace-route-memory";
import {
  clearWorkspaceRouteHistoryState,
  deleteWorkspaceHandoffToken,
} from "@/lib/workspace-route-handoff";
import type { WorkspaceView } from "@/types/resume";

/**
 * Freezes prepared or latest committed data for this mount, then removes the
 * one-time token from browser history before paint.
 */
export function useWorkspaceLateralRouteData<View extends WorkspaceView>(
  view: View,
): WorkspaceLateralRouteDataMap[View] | null {
  const location = useLocation();
  const [resolution] = useState(() =>
    resolveWorkspaceLateralRoute(location.state, view),
  );

  useLayoutEffect(() => {
    if (!resolution.shouldScrubHistory || location.state == null) {
      return;
    }

    deleteWorkspaceHandoffToken(resolution.tokenToDelete);
    clearWorkspaceRouteHistoryState(location.key);
  }, [
    location.key,
    location.state,
    resolution.shouldScrubHistory,
    resolution.tokenToDelete,
  ]);

  return resolution.data;
}

/** Publishes only committed, usable route state to the bounded SPA cache. */
export function useRememberWorkspaceLateralRouteData<
  View extends WorkspaceView,
>(view: View, data: WorkspaceLateralRouteDataMap[View] | null) {
  useLayoutEffect(() => {
    if (data) {
      rememberWorkspaceLateralRoute({
        data,
        view,
      } as PreparedWorkspaceRoute<View>);
    }
  }, [data, view]);
}
