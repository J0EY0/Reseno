import { startTransition, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  clearWorkspaceNavigationError,
  showWorkspaceNavigationError,
} from "@/components/workspace/workspace-navigation-notifications";

import { prepareWorkspaceRoute } from "@/components/workspace/workspace-route-preparation";
import { preloadWorkspaceRoute } from "@/components/workspace/workspace-route-loaders";
import { useWorkspaceNavigationTransaction } from "@/components/workspace/use-workspace-navigation-transaction";
import { isAbortError } from "@/lib/api-client";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import {
  createWorkspaceLateralRouteHandoff,
  type PreparedWorkspaceRoute,
} from "@/lib/workspace-route-memory";
import { getWorkspacePath } from "@/lib/workspace-route";
import { deleteWorkspaceHandoffToken } from "@/lib/workspace-route-handoff";
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

  const preload = useCallback((view: WorkspaceView) => {
    void preloadWorkspaceRoute(view).catch(() => undefined);
  }, []);

  const request = useCallback(
    (view: WorkspaceView) => {
      const intent = beginNavigation();
      const path = getWorkspacePath(view);

      const commitPreparedRoute = (prepared: PreparedWorkspaceRoute) => {
        if (!intent.isCurrent()) {
          return;
        }

        const commitNavigation = async () => {
          if (!intent.isCurrent()) {
            return;
          }

          let handoffToken: string | null = null;
          try {
            const state = createWorkspaceLateralRouteHandoff(prepared);
            handoffToken = state.token;
            intent.finish();
            await navigate(path, { state });
          } catch (error) {
            if (handoffToken) {
              deleteWorkspaceHandoffToken(handoffToken);
            }
            intent.finish();
            console.error("Failed to commit the prepared route.", error);
            showWorkspaceNavigationError(preparationErrorMessage);
          }
        };

        startTransition(commitNavigation);
      };

      const prepareFreshRoute = () => {
        if (!intent.isCurrent()) {
          return;
        }

        clearWorkspaceNavigationError();
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
            showWorkspaceNavigationError(preparationErrorMessage);
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
