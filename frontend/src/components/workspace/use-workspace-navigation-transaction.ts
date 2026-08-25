import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

export interface WorkspaceNavigationIntent {
  cancel: () => void;
  finish: () => void;
  isCurrent: () => boolean;
  signal: AbortSignal;
}

interface ActiveWorkspaceNavigation {
  controller: AbortController;
  id: number;
}

let activeNavigation: ActiveWorkspaceNavigation | null = null;
let nextNavigationId = 0;

function beginWorkspaceNavigation(): WorkspaceNavigationIntent {
  activeNavigation?.controller.abort();

  const id = nextNavigationId + 1;
  nextNavigationId = id;
  const controller = new AbortController();
  activeNavigation = { controller, id };

  const isCurrent = () =>
    activeNavigation?.id === id && !controller.signal.aborted;

  return {
    cancel: () => {
      if (activeNavigation?.id !== id) {
        return;
      }
      controller.abort();
      activeNavigation = null;
    },
    finish: () => {
      if (activeNavigation?.id === id) {
        activeNavigation = null;
      }
    },
    isCurrent,
    signal: controller.signal,
  };
}

/** Gives every same-tab workspace entrance one shared latest-intent owner. */
export function useWorkspaceNavigationTransaction() {
  const location = useLocation();
  const ownedNavigationRef = useRef<WorkspaceNavigationIntent | null>(null);

  const beginNavigation = useCallback(() => {
    const intent = beginWorkspaceNavigation();
    ownedNavigationRef.current = intent;
    return intent;
  }, []);

  const cancelNavigation = useCallback(() => {
    ownedNavigationRef.current?.cancel();
    ownedNavigationRef.current = null;
  }, []);

  useLayoutEffect(() => {
    // Query-only and browser history navigation do not necessarily unmount
    // the owner, but they are still newer same-tab navigation intents.
    cancelNavigation();
  }, [cancelNavigation, location.key]);

  useEffect(
    () => () => {
      cancelNavigation();
    },
    [cancelNavigation],
  );

  return { beginNavigation, cancelNavigation };
}
