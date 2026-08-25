import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import {
  prepareWorkspaceRoute,
  preloadWorkspaceRoute,
  WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
} from "@/components/workspace/workspace-route-preparation";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import { isAbortError } from "@/lib/api-client";
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
  preparationErrorMessage: string;
  requestLeave: (
    commitNavigation: () => void,
    cancelNavigation?: () => void,
  ) => void;
  requiresLeaveResolution: () => boolean;
}

/** Guards the draft, prepares its target, then guards once more before leave. */
export function usePreparedWorkspaceNavigation({
  persistence,
  preparationErrorMessage,
  requestLeave,
  requiresLeaveResolution,
}: PreparedWorkspaceNavigationOptions) {
  const navigate = useNavigate();
  const { beginNavigation, cancelNavigation } =
    useWorkspaceNavigationTransaction();

  const preload = useCallback(
    (view: WorkspaceView) => {
      void preloadWorkspaceRoute(view).catch(() => undefined);
    },
    [],
  );

  const request = useCallback(
    (view: WorkspaceView, transitionType?: "nav-back") => {
      const intent = beginNavigation();
      const path = getWorkspacePath(view);

      const commitPreparedRoute = (prepared: PreparedWorkspaceRoute) => {
        if (!intent.isCurrent()) {
          return;
        }

        const commitNavigation = () => {
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
            console.error("Failed to commit the prepared route.", error);
            toast.error(preparationErrorMessage, {
              closeButton: true,
              id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
            });
          }
        };

        if (transitionType) {
          runViewTransition(commitNavigation, transitionType);
        } else {
          commitNavigation();
        }
      };

      const prepareFreshRoute = () => {
        if (!intent.isCurrent()) {
          return;
        }

        toast.dismiss(WORKSPACE_NAVIGATION_ERROR_TOAST_ID);
        void prepareWorkspaceRoute(view, persistence, {
          signal: intent.signal,
        })
          .then((prepared) => {
            if (!intent.isCurrent()) {
              return;
            }

            // Edits and checkpoint promotion can start while the GET is in
            // flight. Resolve them, then prepare again from server authority.
            if (requiresLeaveResolution()) {
              requestLeave(prepareFreshRoute, intent.cancel);
              return;
            }

            commitPreparedRoute(prepared);
          })
          .catch((error) => {
            if (
              intent.signal.aborted ||
              isAbortError(error) ||
              !intent.isCurrent()
            ) {
              return;
            }
            intent.finish();
            console.error("Failed to prepare the workspace route.", error);
            toast.error(preparationErrorMessage, {
              closeButton: true,
              id: WORKSPACE_NAVIGATION_ERROR_TOAST_ID,
            });
          });
      };

      // The first guard resolves the current draft before the target read.
      requestLeave(prepareFreshRoute, intent.cancel);
    },
    [
      beginNavigation,
      navigate,
      persistence,
      preparationErrorMessage,
      requestLeave,
      requiresLeaveResolution,
    ],
  );

  return { cancelPending: cancelNavigation, preload, request };
}
