import { useCallback, useLayoutEffect, useReducer, useRef } from "react";
import { flushSync } from "react-dom";

import type { ResumeDetailSaveController } from "./use-resume-detail-save";
import type { WorkspaceNavigationIntent } from "./use-workspace-navigation-transaction";

export function useResumeResourceRecovery({
  save: { save, hasUnsavedChanges },
  beginNavigation,
}: {
  save: Pick<ResumeDetailSaveController, "save" | "hasUnsavedChanges">;
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

  return useCallback(
    (signal?: AbortSignal): Promise<void> => {
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
          await save("checkpoint", { notifyOnError: false });
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
    },
    [beginNavigation, hasUnsavedChanges, save],
  );
}
