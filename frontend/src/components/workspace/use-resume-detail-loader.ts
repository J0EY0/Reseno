import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { getMessagesSync, type Locale } from "@/i18n";
import { isAbortError, isApiErrorToastShown } from "@/lib/api-client";
import {
  fetchResumeApi,
  fetchResumeVersionsApi,
  fetchWorkspaceRouteData,
} from "@/lib/workspace-api";
import type { ResumeEditorRouteData } from "@/lib/workspace-route-data";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type {
  ResumeDetailResponse,
  WorkspaceVersionSummary,
} from "@/types/api";

export interface ResumeDetailLoadPayload {
  detail: ResumeDetailResponse;
  routeData: ResumeEditorRouteData;
  versions: WorkspaceVersionSummary[];
}

interface ResumeDetailLoaderOptions {
  hasHandoff: boolean;
  locale: Locale;
  onLoad: (payload: ResumeDetailLoadPayload) => void;
  onLoadErrorChange: (hasLoadError: boolean) => void;
  onLoadingChange: (isLoading: boolean) => void;
  persistence: WorkspacePreferencesPersistence;
  resumeId: string;
}

/** Owns the StrictMode-safe, three-request resume-detail read transaction. */
export function useResumeDetailLoader({
  hasHandoff,
  locale,
  onLoad,
  onLoadErrorChange,
  onLoadingChange,
  persistence,
  resumeId,
}: ResumeDetailLoaderOptions) {
  const initialLocaleRef = useRef(locale);
  const requestIdRef = useRef(0);
  const onLoadRef = useRef(onLoad);
  const onLoadErrorChangeRef = useRef(onLoadErrorChange);
  const onLoadingChangeRef = useRef(onLoadingChange);
  const [retryKey, setRetryKey] = useState(0);
  const [hasLoaded, setHasLoaded] = useState(hasHandoff);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

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
      void import("@/components/preview/document-preview-card");

      try {
        // Preference writes cross route owners; flush before taking a server
        // snapshot, then start all independent detail reads together.
        await persistence.flush();
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        const routeDataRequest = fetchWorkspaceRouteData("resume-detail", {
          notifyOnError: false,
          signal,
        });
        const detailRequest = fetchResumeApi(resumeId, {
          notifyOnError: false,
          signal,
        });
        const versionsRequest = fetchResumeVersionsApi(resumeId, {
          notifyOnError: false,
          signal,
        }).catch((error) => {
          if (isAbortError(error)) {
            throw error;
          }
          return { versions: [] as WorkspaceVersionSummary[] };
        });
        const [routeSource, detail, versionsPayload] = await Promise.all([
          routeDataRequest,
          detailRequest,
          versionsRequest,
        ]);
        if (signal.aborted || requestIdRef.current !== requestId) {
          return;
        }

        onLoadRef.current({
          detail,
          routeData: routeSource.data,
          versions: versionsPayload.versions,
        });
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
