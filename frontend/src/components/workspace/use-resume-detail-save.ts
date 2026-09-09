import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { useAuthSessionToken } from "@/hooks/use-auth-session-token";
import type { AgentDraftConflictResolution } from "@/lib/agent-draft-review";
import {
  resolveAgentDraftDecision,
  type AgentDraftDecisionResolution,
} from "@/lib/agent-session-run-client";
import {
  countResumeChanges,
  createResumeFingerprint,
} from "@/lib/workspace-change-tracking";
import {
  fetchResumeVersionApi,
  fetchResumeVersionsApi,
  saveResumeApi,
} from "@/lib/workspace-api";
import type {
  AgentDraftDecisionStatus,
  ApiRequestOptions,
  ResumeDetailResponse,
  ResumeSaveMode,
  SaveResponse,
  WorkspaceVersionSummary,
} from "@/types/api";
import type { ResumeData, ResumeWorkspaceItem } from "@/types/resume";

const AUTOSAVE_DELAY_MS = 5_000;
const AUTOSAVE_MAX_WAIT_MS = 30_000;
const AUTOSAVE_RETRY_DELAYS_MS = [2_000, 5_000] as const;

type ResumeDetailSaveState = "idle" | "saving" | "saved";

interface ActiveResumeSave {
  promise: Promise<SaveResponse>;
  resumeId: string;
}

interface PersistedResumeState {
  resume: ResumeWorkspaceItem | null;
  fingerprint: string;
  savedAt: string | null;
  versionId: string | null;
  saveMode: ResumeSaveMode;
}

interface ResumeDetailSaveOptions {
  getFingerprint: () => string;
  getSnapshot: (updatedAt: string) => ResumeWorkspaceItem | null;
  initialCheckpoint?: { savedAt: string; versionId: string };
  initialResume: ResumeWorkspaceItem | null;
  isLoading: boolean;
  liveFingerprint: string;
  liveResume: ResumeWorkspaceItem | null;
  messages: AppMessages;
  onAdoptSavedResume: (
    resume: ResumeWorkspaceItem,
    submitted: ResumeWorkspaceItem,
  ) => void;
  onHydrateResume: (resume: ResumeWorkspaceItem) => void;
  resumeId: string;
}

/** Owns resume persistence, history metadata, and the autosave transaction. */
export function useResumeDetailSave({
  getFingerprint,
  getSnapshot,
  initialCheckpoint,
  initialResume,
  isLoading,
  liveFingerprint,
  liveResume,
  messages,
  onAdoptSavedResume,
  onHydrateResume,
  resumeId,
}: ResumeDetailSaveOptions) {
  const authToken = useAuthSessionToken();
  const [persisted, setPersisted] = useState<PersistedResumeState>(() => ({
    resume: initialResume,
    fingerprint: createResumeFingerprint(initialResume),
    savedAt: initialCheckpoint?.savedAt ?? initialResume?.updatedAt ?? null,
    versionId: initialCheckpoint?.versionId ?? null,
    saveMode: "checkpoint",
  }));
  const persistedRef = useRef(persisted);
  const { savedAt: lastSavedAt, versionId: activeVersionId } = persisted;
  const changeCount = useMemo(
    () => countResumeChanges(persisted.resume, liveResume),
    [persisted.resume, liveResume],
  );
  const [versions, setVersions] = useState<WorkspaceVersionSummary[]>(
    initialCheckpoint ? [initialCheckpoint] : [],
  );
  const [saveState, setSaveState] = useState<ResumeDetailSaveState>(
    initialCheckpoint ? "saved" : "idle",
  );
  const [isVersionLoading, setIsVersionLoading] = useState(false);
  const [hasVersionLoadError, setHasVersionLoadError] = useState(false);
  const activeRequestRef = useRef<ActiveResumeSave | null>(null);
  const recentlySavedFingerprintsRef = useRef<Set<string>>(new Set());
  const autosaveBurstStartedAtRef = useRef<number | null>(null);
  const autosaveGenerationRef = useRef(0);
  const autosaveRetryAttemptRef = useRef(0);
  const skipCheckpointPromotionRef = useRef(false);
  const versionLoadRequestRef = useRef<AbortController | null>(null);
  const ownerLifecycleRef = useRef<symbol | null>(null);

  useEffect(() => {
    const owner = Symbol("resume-detail-save-owner");
    ownerLifecycleRef.current = owner;
    return () => {
      if (ownerLifecycleRef.current === owner) {
        ownerLifecycleRef.current = null;
        versionLoadRequestRef.current?.abort();
        versionLoadRequestRef.current = null;
      }
    };
  }, [resumeId]);

  const adoptPersistedBaseline = useCallback(
    (detail: ResumeDetailResponse, saveMode: ResumeSaveMode) => {
      const fingerprint = createResumeFingerprint(detail.resume);
      const baseline = { ...detail, fingerprint, saveMode };
      persistedRef.current = baseline;
      setPersisted(baseline);
      skipCheckpointPromotionRef.current = false;
      setSaveState("saved");
      return fingerprint;
    },
    [],
  );

  const adoptPersistedSave = useCallback(
    (
      saved: ResumeDetailResponse,
      submitted: ResumeWorkspaceItem,
      saveMode: ResumeSaveMode,
    ) => {
      const savedFingerprint = adoptPersistedBaseline(saved, saveMode);
      recentlySavedFingerprintsRef.current = new Set([
        createResumeFingerprint(submitted),
        savedFingerprint,
      ]);
      onAdoptSavedResume(saved.resume, submitted);
    },
    [adoptPersistedBaseline, onAdoptSavedResume],
  );

  const hasUnsavedChanges = useCallback(() => {
    const fingerprint = getFingerprint();
    return Boolean(
      fingerprint && fingerprint !== persistedRef.current.fingerprint,
    );
  }, [getFingerprint]);

  const hydratePersistedResume = useCallback(
    (detail: ResumeDetailResponse, nextVersions: WorkspaceVersionSummary[]) => {
      autosaveGenerationRef.current += 1;
      const saveMode = nextVersions.some(
        (version) => version.versionId === detail.versionId,
      )
        ? "checkpoint"
        : "autosave";
      adoptPersistedBaseline(detail, saveMode);
      setVersions(nextVersions);
      setHasVersionLoadError(false);
    },
    [adoptPersistedBaseline],
  );

  const save = useCallback(
    async (
      saveMode: ResumeSaveMode = "checkpoint",
      options: Pick<ApiRequestOptions, "notifyOnError"> = {},
    ): Promise<ResumeDetailResponse> => {
      let latestCompletedSave: SaveResponse | null = null;

      while (activeRequestRef.current) {
        const activeRequest = activeRequestRef.current;
        try {
          latestCompletedSave = await activeRequest.promise;
        } catch {
          // A queued intent retries the latest snapshot after an older failure.
        } finally {
          if (activeRequestRef.current === activeRequest) {
            activeRequestRef.current = null;
          }
        }
      }

      const effectiveLastSavedAt =
        latestCompletedSave?.savedAt ?? persistedRef.current.savedAt;
      const effectiveVersionId =
        latestCompletedSave?.versionId ??
        persistedRef.current.versionId ??
        undefined;
      const stableResume = getSnapshot(effectiveLastSavedAt ?? "");
      if (!stableResume || stableResume.id !== resumeId) {
        throw new Error("No active resume is available to save.");
      }
      const stableFingerprint = getFingerprint();
      const requiresCheckpointPromotion =
        saveMode === "checkpoint" &&
        persistedRef.current.saveMode === "autosave";

      if (
        stableFingerprint === persistedRef.current.fingerprint &&
        !requiresCheckpointPromotion &&
        effectiveLastSavedAt &&
        effectiveVersionId &&
        persistedRef.current.resume
      ) {
        setSaveState("saved");
        return {
          resume: persistedRef.current.resume,
          savedAt: effectiveLastSavedAt,
          versionId: effectiveVersionId,
        };
      }

      const request = (async (): Promise<ResumeDetailResponse> => {
        setSaveState("saving");
        recentlySavedFingerprintsRef.current.clear();
        try {
          const saved = await saveResumeApi(
            stableResume.id,
            {
              documentLocale: stableResume.documentLocale,
              jobBrief: stableResume.jobBrief,
              resume: stableResume.resume,
              template: stableResume.template,
              templateSettings: stableResume.templateSettings ?? null,
              title: stableResume.title,
              typography: stableResume.typography,
            },
            saveMode,
            options,
          );
          adoptPersistedSave(saved, stableResume, saveMode);

          if (saveMode === "checkpoint") {
            try {
              const payload = await fetchResumeVersionsApi(saved.resume.id);
              setVersions(payload.versions);
            } catch (versionsError) {
              console.error(
                "Failed to refresh resume versions.",
                versionsError,
              );
            }
          }

          return saved;
        } catch (error) {
          setSaveState("idle");
          throw error;
        }
      })();
      const trackedRequest = { promise: request, resumeId };
      activeRequestRef.current = trackedRequest;

      try {
        return await request;
      } finally {
        if (activeRequestRef.current === trackedRequest) {
          activeRequestRef.current = null;
        }
      }
    },
    [adoptPersistedSave, getFingerprint, getSnapshot, resumeId],
  );

  const resolveAgentDraftReview = useCallback(
    async (
      messageId: string,
      currentResume: ResumeData,
      reviewItemIds: string[],
      status: AgentDraftDecisionStatus,
      conflictResolution?: AgentDraftConflictResolution,
    ): Promise<AgentDraftDecisionResolution> => {
      const owner = ownerLifecycleRef.current;
      const requireCurrentOwner = () => {
        if (!owner || ownerLifecycleRef.current !== owner) {
          throw new DOMException(
            "The resume detail save owner is no longer active.",
            "AbortError",
          );
        }
      };

      while (activeRequestRef.current) {
        const activeRequest = activeRequestRef.current;
        try {
          await activeRequest.promise;
        } catch {
          // The apply reads fresh formal/session revisions after the failed save.
        } finally {
          if (activeRequestRef.current === activeRequest) {
            activeRequestRef.current = null;
          }
        }
        requireCurrentOwner();
      }
      requireCurrentOwner();
      const hasLocalChanges = hasUnsavedChanges();
      const resolutionPromise = (async () => {
        if (status === "applied") {
          setSaveState("saving");
        }
        try {
          const resolution = await resolveAgentDraftDecision(
            resumeId,
            messageId,
            status === "applied"
              ? {
                  conflictResolution,
                  currentResume,
                  currentVersionId: persistedRef.current.versionId,
                  rebaseOnLatest: !hasLocalChanges,
                  reviewItemIds,
                  status,
                }
              : { reviewItemIds, status },
          );
          const canAdoptFormalResume =
            !hasLocalChanges ||
            (status === "applied" &&
              resolution.committed &&
              resolution.resolvedAsRequested);
          const adoptedResume = canAdoptFormalResume ? resolution.resume : null;
          if (adoptedResume) {
            adoptPersistedSave(adoptedResume, adoptedResume.resume, "autosave");
          } else if (status === "applied") {
            setSaveState("idle");
          }
          return { ...resolution, resume: adoptedResume };
        } catch (error) {
          if (status === "applied") {
            setSaveState("idle");
          }
          throw error;
        }
      })();
      const trackedRequest: ActiveResumeSave = {
        promise: resolutionPromise.then((resolution) => ({
          savedAt:
            resolution.resume?.savedAt ?? persistedRef.current.savedAt ?? "",
          versionId:
            resolution.resume?.versionId ??
            persistedRef.current.versionId ??
            undefined,
        })),
        resumeId,
      };
      activeRequestRef.current = trackedRequest;

      try {
        return await resolutionPromise;
      } finally {
        if (activeRequestRef.current === trackedRequest) {
          activeRequestRef.current = null;
        }
      }
    },
    [adoptPersistedSave, hasUnsavedChanges, resumeId],
  );

  const discard = useCallback(async () => {
    const persistedResume = persistedRef.current.resume;
    if (!persistedResume) {
      return;
    }

    const activeRequest = activeRequestRef.current;
    const hasActiveSave = activeRequest?.resumeId === persistedResume.id;
    const shouldCheckpoint =
      hasActiveSave || persistedRef.current.saveMode === "autosave";

    autosaveGenerationRef.current += 1;
    onHydrateResume(persistedResume);

    if (hasActiveSave) {
      try {
        await activeRequest.promise;
      } catch {
        // The captured persisted snapshot below remains the discard authority.
      }
    }

    if (!shouldCheckpoint) {
      setSaveState("saved");
      return;
    }

    const restored = await saveResumeApi(
      persistedResume.id,
      {
        documentLocale: persistedResume.documentLocale,
        jobBrief: persistedResume.jobBrief,
        resume: persistedResume.resume,
        template: persistedResume.template,
        templateSettings: persistedResume.templateSettings ?? null,
        title: persistedResume.title,
        typography: persistedResume.typography,
      },
      "checkpoint",
    );
    adoptPersistedBaseline(restored, "checkpoint");
    onHydrateResume(restored.resume);
  }, [adoptPersistedBaseline, onHydrateResume]);

  const selectVersion = useCallback(
    async (versionId: string) => {
      const owner = ownerLifecycleRef.current;
      if (
        !owner ||
        versionId === persistedRef.current.versionId ||
        versionLoadRequestRef.current ||
        activeRequestRef.current
      ) {
        return;
      }

      const controller = new AbortController();
      versionLoadRequestRef.current = controller;
      const requestedFingerprint = getFingerprint();
      setIsVersionLoading(true);
      setHasVersionLoadError(false);
      try {
        const detail = await fetchResumeVersionApi(resumeId, versionId, {
          signal: controller.signal,
        });
        if (
          controller.signal.aborted ||
          ownerLifecycleRef.current !== owner ||
          getFingerprint() !== requestedFingerprint
        ) {
          return;
        }
        onHydrateResume(detail.resume);
        hydratePersistedResume(detail, versions);
      } catch (error) {
        if (controller.signal.aborted || ownerLifecycleRef.current !== owner) {
          return;
        }
        console.error("Failed to load resume version.", error);
        setHasVersionLoadError(true);
        setSaveState("idle");
      } finally {
        if (versionLoadRequestRef.current === controller) {
          versionLoadRequestRef.current = null;
          setIsVersionLoading(false);
        }
      }
    },
    [
      getFingerprint,
      hydratePersistedResume,
      onHydrateResume,
      resumeId,
      versions,
    ],
  );

  useEffect(() => {
    autosaveGenerationRef.current += 1;
    autosaveBurstStartedAtRef.current = null;
    autosaveRetryAttemptRef.current = 0;
    toast.dismiss("autosave-failed");
  }, [resumeId, authToken]);

  useEffect(() => {
    if (!authToken || isLoading) {
      return;
    }
    if (!hasUnsavedChanges()) {
      autosaveBurstStartedAtRef.current = null;
      autosaveRetryAttemptRef.current = 0;
      toast.dismiss("autosave-failed");
      return;
    }

    const now = Date.now();
    const burstStartedAt = autosaveBurstStartedAtRef.current ?? now;
    const generation = autosaveGenerationRef.current;
    const maxWaitRemaining = Math.max(
      0,
      AUTOSAVE_MAX_WAIT_MS - (now - burstStartedAt),
    );
    let cancelled = false;
    let timer: number | null = null;
    autosaveBurstStartedAtRef.current = burstStartedAt;

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => void runAutosave(), delay);
    };
    const runAutosave = async () => {
      if (
        cancelled ||
        generation !== autosaveGenerationRef.current ||
        !hasUnsavedChanges()
      ) {
        return;
      }
      try {
        await save("autosave", { notifyOnError: false });
        if (cancelled || generation !== autosaveGenerationRef.current) {
          return;
        }
        autosaveBurstStartedAtRef.current = null;
        autosaveRetryAttemptRef.current = 0;
        toast.dismiss("autosave-failed");
      } catch (error) {
        if (
          cancelled ||
          generation !== autosaveGenerationRef.current ||
          !hasUnsavedChanges()
        ) {
          return;
        }
        const retryDelay =
          AUTOSAVE_RETRY_DELAYS_MS[autosaveRetryAttemptRef.current];
        if (typeof retryDelay === "number") {
          autosaveRetryAttemptRef.current += 1;
          schedule(retryDelay);
          return;
        }
        console.warn("Failed to autosave resume after retries.", error);
        autosaveBurstStartedAtRef.current = null;
        autosaveRetryAttemptRef.current = 0;
        toast.error(messages.loadError, {
          closeButton: true,
          id: "autosave-failed",
        });
      }
    };

    schedule(Math.min(AUTOSAVE_DELAY_MS, maxWaitRemaining));
    return () => {
      cancelled = true;
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [
    authToken,
    hasUnsavedChanges,
    isLoading,
    lastSavedAt,
    liveFingerprint,
    messages.loadError,
    save,
  ]);

  useEffect(() => {
    if (isLoading || saveState === "saving") {
      return;
    }
    if (liveFingerprint === persistedRef.current.fingerprint) {
      return;
    }
    if (
      saveState === "saved" &&
      recentlySavedFingerprintsRef.current.has(liveFingerprint)
    ) {
      return;
    }
    setSaveState("idle");
  }, [isLoading, liveFingerprint, saveState]);

  useEffect(() => {
    if (saveState !== "saved") {
      return;
    }
    const timer = window.setTimeout(() => setSaveState("idle"), 1_800);
    return () => window.clearTimeout(timer);
  }, [saveState]);

  return {
    activeVersionId,
    changeCount,
    discard,
    hasUnsavedChanges,
    hasVersionLoadError,
    hydratePersistedResume,
    isVersionLoading,
    lastSavedAt,
    markCheckpointPromotionSkipped: () => {
      skipCheckpointPromotionRef.current = true;
    },
    requiresCheckpointPromotion: () =>
      persistedRef.current.saveMode === "autosave" &&
      !skipCheckpointPromotionRef.current,
    save,
    saveState,
    resolveAgentDraftReview,
    selectVersion,
    versions,
  };
}

export type ResumeDetailSaveController = ReturnType<typeof useResumeDetailSave>;
