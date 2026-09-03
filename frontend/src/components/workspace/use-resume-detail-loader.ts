import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { getMessagesSync, type Locale } from "@/i18n";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import { loadDocumentCanvas } from "@/components/preview/document-canvas-loader";
import { loadResumeDetailRouteData } from "@/components/workspace/workspace-route-preparation";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";

interface ResumeDetailLoaderOptions {
  hasHandoff: boolean;
  initialPreparedData: PreparedResumeDetailRouteData | null;
  locale: Locale;
  onLoad: (payload: PreparedResumeDetailRouteData) => void;
  onLoadErrorChange: (hasLoadError: boolean) => void;
  onLoadingChange: (isLoading: boolean) => void;
  persistence: WorkspacePreferencesPersistence;
  resumeId: string;
}

/** Owns the StrictMode-safe, three-request resume-detail read transaction. */
export function useResumeDetailLoader({
  hasHandoff,
  initialPreparedData,
  locale,
  onLoad,
  onLoadErrorChange,
  onLoadingChange,
  persistence,
  resumeId,
}: ResumeDetailLoaderOptions) {
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const initialPreparedDataRef = useRef(initialPreparedData);
  const hasConsumedInitialPreparedDataRef = useRef(false);
  const onLoadRef = useRef(onLoad);
  const onLoadErrorChangeRef = useRef(onLoadErrorChange);
  const onLoadingChangeRef = useRef(onLoadingChange);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(hasHandoff);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(!initialPreparedData);

  useEffect(() => {
    onLoadRef.current = onLoad;
    onLoadErrorChangeRef.current = onLoadErrorChange;
    onLoadingChangeRef.current = onLoadingChange;
  }, [onLoad, onLoadErrorChange, onLoadingChange]);

  const load = useCallback(
    async (signal: AbortSignal) => {
      const requestId = requestIdRef.current + 1;
      requestIdRef.current = requestId;
      setIsLoading(true);
      onLoadingChangeRef.current(true);
      setHasLoadError(false);
      onLoadErrorChangeRef.current(false);
      toast.dismiss("workspace-load-error");
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
        if (!isApiErrorToastShown(error)) {
          toast.error(
            getMessagesSync(initialLocaleRef.current).apiMessages
              .REQUEST_FAILED,
            { closeButton: true, id: "workspace-load-error" },
          );
        }
        setHasLoadError(true);
        onLoadErrorChangeRef.current(true);
      } finally {
        if (requestIdRef.current === requestId) {
          setIsLoading(false);
          onLoadingChangeRef.current(false);
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
        onLoadErrorChangeRef.current(false);
        onLoadingChangeRef.current(false);
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
