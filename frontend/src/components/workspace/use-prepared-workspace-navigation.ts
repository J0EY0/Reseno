import { useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { prepareWorkspaceRoute } from "@/components/workspace/workspace-route-preparation";
import { runViewTransition } from "@/lib/view-transition";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  createWorkspaceLateralRouteHandoff,
  deleteWorkspaceLateralRouteHandoff,
  type PreparedWorkspaceRoute,
} from "@/lib/workspace-route-memory";
import { getWorkspacePath } from "@/lib/workspace-route";
import type { WorkspaceView } from "@/types/resume";

interface PreparedWorkspaceNavigationOptions {
  persistence: WorkspacePreferencesPersistence;
  requestLeave: (commitNavigation: () => void) => void;
}

/** Guards the draft, prepares its target, then guards once more before leave. */
export function usePreparedWorkspaceNavigation({
  persistence,
  requestLeave,
}: PreparedWorkspaceNavigationOptions) {
  const navigate = useNavigate();
  const navigationIntentRef = useRef(0);

  const cancelPending = useCallback(() => {
    navigationIntentRef.current += 1;
  }, []);

  useEffect(
    () => () => {
      cancelPending();
    },
    [cancelPending],
  );

  const preload = useCallback(
    (view: WorkspaceView) => {
      void prepareWorkspaceRoute(view, persistence).catch(() => undefined);
    },
    [persistence],
  );

  const request = useCallback(
    (view: WorkspaceView, transitionType?: "nav-back") => {
      const intentId = navigationIntentRef.current + 1;
      navigationIntentRef.current = intentId;
      const path = getWorkspacePath(view);

      const finishPreparation = (
        prepared: PreparedWorkspaceRoute | null,
      ) => {
        if (navigationIntentRef.current !== intentId) {
          return;
        }

        // Guard again in case the draft changed while preparation was pending.
        requestLeave(() => {
          if (navigationIntentRef.current !== intentId) {
            return;
          }

          const commitNavigation = () => {
            let handoffToken: string | null = null;
            try {
              if (!prepared) {
                navigate(path);
                return;
              }

              const state = createWorkspaceLateralRouteHandoff(prepared);
              handoffToken = state.token;
              navigate(path, { state });
            } catch {
              if (handoffToken) {
                deleteWorkspaceLateralRouteHandoff(handoffToken);
              }
              navigate(path);
            }
          };
          if (transitionType) {
            runViewTransition(commitNavigation, transitionType);
          } else {
            commitNavigation();
          }
        });
      };

      // Guard immediately for responsive dirty-state feedback. Formal
      // preparation starts after Save/Discard so mutations invalidate its GET.
      requestLeave(() => {
        void prepareWorkspaceRoute(view, persistence).then(
          finishPreparation,
          () => finishPreparation(null),
        );
      });
    },
    [navigate, persistence, requestLeave],
  );

  return { cancelPending, preload, request };
}
