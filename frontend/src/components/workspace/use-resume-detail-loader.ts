import { useCallback, useEffect, useRef, useState } from "react";

import { getMessagesSync, type Locale } from "@/i18n";
import { isAbortError } from "@/lib/api-client";
import {
  dismissWorkspaceLoadError,
  showWorkspaceLoadError,
} from "@/lib/workspace-load-error";
import { loadDocumentCanvas } from "@/components/preview/document-canvas-loader";
import { loadResumeDetailRouteData } from "@/components/workspace/workspace-route-preparation";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

interface ResumeDetailLoaderOptions {
  initialPreparedData: PreparedResumeDetailRouteData | null;
  locale: Locale;
  onLoad: (payload: PreparedResumeDetailRouteData) => void;
  persistence: WorkspacePreferencesPersistence;
  resumeId: string;
}

/** Owns the StrictMode-safe, three-request resume-detail read transaction. */
export function useResumeDetailLoader({
  initialPreparedData,
  locale,
  onLoad,
  persistence,
  resumeId,
}: ResumeDetailLoaderOptions) {
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const initialPreparedDataRef = useRef(initialPreparedData);
  const hasConsumedInitialPreparedDataRef = useRef(false);
  const onLoadRef = useRef(onLoad);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(Boolean(initialPreparedData));
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!initialPreparedData);

  useEffect(() => {
    onLoadRef.current = onLoad;
  }, [onLoad]);

  const load = useCallback(
    async (signal: AbortSignal) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setIsLoading(true);
      setHasLoadError(false);
      dismissWorkspaceLoadError();
      void loadDocumentCanvas();

      try {
        const prepared = await loadResumeDetailRouteData(
          resumeId,
          persistence,
          { signal },
        );
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        onLoadRef.current(prepared);
        setHasLoaded(true);
      } catch (error) {
        if (isAbortError(error) || requestIdRef.current !== requestId) {
          return;
        }
        console.error("Failed to load the resume detail route.", error);
        showWorkspaceLoadError(
          error,
          getMessagesSync(initialLocaleRef.current).apiMessages.REQUEST_FAILED,
        );
        setHasLoadError(true);
      } finally {
        if (requestIdRef.current === requestId) {
          setIsLoading(false);
        }
      }
    },
    [persistence, resumeId],
  );

  useEffect(() => {
    const prepared = initialPreparedDataRef.current;
    if (prepared && retryKey === 0) {
      if (!hasConsumedInitialPreparedDataRef.current) {
        hasConsumedInitialPreparedDataRef.current = true;
        onLoadRef.current(prepared);
        setHasLoaded(true);
        setHasLoadError(false);
        setIsLoading(false);
      }
      return;
    }

    const controller = new AbortController();
    // Delay one task so StrictMode's development preflight sends no request.
    const loadTimer = window.setTimeout(() => {
      if (!controller.signal.aborted) {
        void load(controller.signal);
      }
    }, 0);

    return () => {
      window.clearTimeout(loadTimer);
      controller.abort();
    };
  }, [load, retryKey]);

  return {
    hasLoaded,
    hasLoadError,
    isLoading,
    retryLoad: () => setRetryKey((current) => current + 1),
  };
}
