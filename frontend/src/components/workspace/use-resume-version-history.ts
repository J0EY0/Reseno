import { useCallback, useEffect, useRef, useState } from "react";

import { loadMessages } from "@/i18n";
import { fetchResumeVersionApi } from "@/lib/workspace-api";
import type { ResumeDetailResponse } from "@/types/api";
import type { ResumeWorkspaceItem } from "@/types/resume";

interface ResumeVersionHistoryOptions {
  getCurrentVersionId: () => string | null;
  getFingerprint: () => string;
  isBusy: () => boolean;
  onRestore: (resume: ResumeWorkspaceItem) => void;
  restoreSnapshot: (
    snapshot: ResumeWorkspaceItem,
  ) => Promise<ResumeDetailResponse>;
  resumeId: string;
}

export function useResumeVersionHistory({
  getCurrentVersionId,
  getFingerprint,
  isBusy,
  onRestore,
  restoreSnapshot,
  resumeId,
}: ResumeVersionHistoryOptions) {
  const [historyVersion, setHistoryVersion] =
    useState<ResumeDetailResponse | null>(null);
  const [isVersionLoading, setIsVersionLoading] = useState(false);
  const [hasVersionLoadError, setHasVersionLoadError] = useState(false);
  const [hasVersionRestoreError, setHasVersionRestoreError] = useState(false);
  const [isRestoringVersion, setIsRestoringVersion] = useState(false);
  const restoringRef = useRef(false);
  const requestRef = useRef<AbortController | null>(null);
  const ownerRef = useRef<symbol | null>(null);

  useEffect(() => {
    const owner = Symbol(resumeId);
    ownerRef.current = owner;
    return () => {
      if (ownerRef.current === owner) {
        ownerRef.current = null;
        requestRef.current?.abort();
        requestRef.current = null;
      }
    };
  }, [resumeId]);

  const returnToLatest = useCallback(() => {
    if (restoringRef.current) return;
    requestRef.current?.abort();
    requestRef.current = null;
    setHistoryVersion(null);
    setIsVersionLoading(false);
    setHasVersionLoadError(false);
    setHasVersionRestoreError(false);
  }, []);

  const selectVersion = useCallback(
    async (versionId: string) => {
      if (restoringRef.current) return;
      if (versionId === getCurrentVersionId()) {
        returnToLatest();
        return;
      }
      if (versionId === historyVersion?.versionId) return;
      const owner = ownerRef.current;
      if (!owner || requestRef.current || isBusy()) return;

      const controller = new AbortController();
      requestRef.current = controller;
      const fingerprint = getFingerprint();
      setIsVersionLoading(true);
      setHasVersionLoadError(false);
      setHasVersionRestoreError(false);
      try {
        const detail = await fetchResumeVersionApi(resumeId, versionId, {
          signal: controller.signal,
        });
        await loadMessages(detail.resume.documentLocale);
        if (
          controller.signal.aborted ||
          ownerRef.current !== owner ||
          getFingerprint() !== fingerprint
        )
          return;
        setHistoryVersion(detail);
      } catch (error) {
        if (controller.signal.aborted || ownerRef.current !== owner) return;
        console.error("Failed to load resume version.", error);
        setHasVersionLoadError(true);
      } finally {
        if (requestRef.current === controller) {
          requestRef.current = null;
          setIsVersionLoading(false);
        }
      }
    },
    [
      getCurrentVersionId,
      getFingerprint,
      historyVersion?.versionId,
      isBusy,
      resumeId,
      returnToLatest,
    ],
  );

  const restoreVersion = useCallback(async () => {
    const owner = ownerRef.current;
    if (!historyVersion || !owner || restoringRef.current || isBusy())
      return false;
    requestRef.current?.abort();
    requestRef.current = null;
    setIsVersionLoading(false);
    restoringRef.current = true;
    setIsRestoringVersion(true);
    setHasVersionRestoreError(false);
    try {
      const restored = await restoreSnapshot(historyVersion.resume);
      if (ownerRef.current !== owner) return false;
      onRestore(restored.resume);
      setHistoryVersion(null);
      return true;
    } catch (error) {
      if (ownerRef.current === owner) {
        console.error("Failed to restore resume version.", error);
        setHasVersionRestoreError(true);
      }
      return false;
    } finally {
      restoringRef.current = false;
      if (ownerRef.current === owner) setIsRestoringVersion(false);
    }
  }, [historyVersion, isBusy, onRestore, restoreSnapshot]);

  return {
    hasVersionLoadError,
    hasVersionRestoreError,
    historyVersion,
    isVersionLoading,
    isRestoringVersion,
    isViewingHistory: historyVersion !== null,
    returnToLatest,
    restoreVersion,
    selectVersion,
  };
}
