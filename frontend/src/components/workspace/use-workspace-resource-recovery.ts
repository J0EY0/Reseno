import { useLayoutEffect, useReducer, useRef } from "react";
import { flushSync } from "react-dom";

import type { WorkspaceNavigationIntent } from "./use-workspace-navigation-transaction";

export function useWorkspaceResourceRecovery({
  saveCheckpoint,
  hasUnsavedChanges,
  beginNavigation,
}: {
  saveCheckpoint: () => Promise<unknown>;
  hasUnsavedChanges: () => boolean;
  beginNavigation: () => WorkspaceNavigationIntent;
}) {
  const requestRef = useRef<Promise<void> | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);
  const mountedRef = useRef(false);
  const [, commit] = useReducer((revision: number) => revision + 1, 0);

  useLayoutEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cancelRef.current?.();
    };
  }, []);

  return function saveAndReload(signal?: AbortSignal): Promise<void> {
    if (signal?.aborted || !mountedRef.current) {
      return Promise.reject(
        signal?.reason ??
          new DOMException("Resource recovery was cancelled.", "AbortError"),
      );
    }
    if (requestRef.current) {
      return requestRef.current;
    }

    const intent = beginNavigation();
    cancelRef.current = intent.cancel;
    const requireCurrent = () => {
      signal?.throwIfAborted();
      if (!intent.isCurrent()) {
        throw new DOMException(
          "Resource recovery was cancelled.",
          "AbortError",
        );
      }
    };
    const recover = async () => {
      requireCurrent();
      flushSync(commit);
      do {
        requireCurrent();
        await saveCheckpoint();
        requireCurrent();
        flushSync(commit);
        requireCurrent();
      } while (hasUnsavedChanges());
      intent.finish();
      window.location.reload();
    };
    const request = recover().finally(() => {
      intent.cancel();
      cancelRef.current = null;
      requestRef.current = null;
    });
    requestRef.current = request;
    return request;
  };
}
