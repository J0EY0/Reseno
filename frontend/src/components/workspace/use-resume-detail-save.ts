import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
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

export type ResumeDetailSaveState = "idle" | "saving" | "saved";

interface ActiveResumeSave {
  promise: Promise<SaveResponse>;
  resumeId: string;
}

interface ResumeDetailSaveOptions {
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
  const initialSavedAt =
    initialCheckpoint?.savedAt ?? initialResume?.updatedAt ?? null;
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(initialSavedAt);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(
    initialCheckpoint?.versionId ?? null,
  );
  const [versions, setVersions] = useState<WorkspaceVersionSummary[]>(
    initialCheckpoint ? [initialCheckpoint] : [],
  );
  const [saveState, setSaveState] = useState<ResumeDetailSaveState>(
    initialCheckpoint ? "saved" : "idle",
  );
  const [isVersionLoading, setIsVersionLoading] = useState(false);
  const [hasVersionLoadError, setHasVersionLoadError] = useState(false);
  const [persistedResume, setPersistedResume] =
    useState<ResumeWorkspaceItem | null>(initialResume);
  const activeRequestRef = useRef<ActiveResumeSave | null>(null);
  const activeVersionIdRef = useRef(activeVersionId);
  const lastSavedAtRef = useRef(lastSavedAt);
  const lastSaveModeRef = useRef<ResumeSaveMode>("checkpoint");
  const persistedFingerprintRef = useRef(
    createResumeFingerprint(initialResume),
  );
  const persistedResumeRef = useRef<ResumeWorkspaceItem | null>(initialResume);
  const persistenceEpochRef = useRef(0);
  const recentlySavedFingerprintsRef = useRef<Set<string>>(new Set());
  const autosaveBurstStartedAtRef = useRef<number | null>(null);
  const autosaveGenerationRef = useRef(0);
  const autosaveRetryAttemptRef = useRef(0);
  const skipCheckpointPromotionRef = useRef(false);
  const versionLoadRequestRef = useRef<string | null>(null);

  const adoptPersistedSave = useCallback(
    (
      saved: ResumeDetailResponse,
      submitted: ResumeWorkspaceItem,
      saveMode: ResumeSaveMode,
    ) => {
      const savedFingerprint = createResumeFingerprint(saved.resume);
      persistedResumeRef.current = saved.resume;
      persistenceEpochRef.current += 1;
      setPersistedResume(saved.resume);
      persistedFingerprintRef.current = savedFingerprint;
      recentlySavedFingerprintsRef.current = new Set([
        createResumeFingerprint(submitted),
        savedFingerprint,
      ]);
      lastSaveModeRef.current = saveMode;
      skipCheckpointPromotionRef.current = false;
      lastSavedAtRef.current = saved.savedAt;
      activeVersionIdRef.current = saved.versionId;
      onAdoptSavedResume(saved.resume, submitted);
      setLastSavedAt(saved.savedAt);
      setActiveVersionId(saved.versionId);
      setSaveState("saved");
    },
    [onAdoptSavedResume],
  );

  const hasUnsavedChanges = useCallback(
    () =>
      Boolean(
        getSnapshot(lastSavedAtRef.current ?? "") &&
          createResumeFingerprint(
            getSnapshot(lastSavedAtRef.current ?? ""),
          ) !== persistedFingerprintRef.current,
      ),
    [getSnapshot],
  );

  const hydratePersistedResume = useCallback(
    (
      detail: ResumeDetailResponse,
      nextVersions: WorkspaceVersionSummary[],
      expectedPersistedFingerprint?: string,
    ) => {
      if (
        expectedPersistedFingerprint &&
        (persistedFingerprintRef.current !== expectedPersistedFingerprint ||
          persistenceEpochRef.current !== 0)
      ) {
        return false;
      }

      autosaveGenerationRef.current += 1;
      persistedResumeRef.current = detail.resume;
      setPersistedResume(detail.resume);
      persistedFingerprintRef.current = createResumeFingerprint(detail.resume);
      lastSavedAtRef.current = detail.savedAt;
      activeVersionIdRef.current = detail.versionId;
      lastSaveModeRef.current = nextVersions.some(
        (version) => version.versionId === detail.versionId,
      )
        ? "checkpoint"
        : "autosave";
      skipCheckpointPromotionRef.current = false;
      setLastSavedAt(detail.savedAt);
      setActiveVersionId(detail.versionId);
      setVersions(nextVersions);
      setHasVersionLoadError(false);
      setSaveState("saved");
      return true;
    },
    [],
  );

  const save = useCallback(
    async (
      saveMode: ResumeSaveMode = "checkpoint",
      options: Pick<ApiRequestOptions, "notifyOnError"> = {},
    ): Promise<SaveResponse> => {
      let latestCompletedSave: SaveResponse | null = null;

      // One route owns one resume. Serializing intents keeps export and leave
      // actions from observing an older save while a newer snapshot is queued.
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
        latestCompletedSave?.savedAt ?? lastSavedAtRef.current;
      const effectiveVersionId =
        latestCompletedSave?.versionId ??
        activeVersionIdRef.current ??
        undefined;
      const stableResume = getSnapshot(effectiveLastSavedAt ?? "");
      const stableFingerprint = createResumeFingerprint(stableResume);
      const requiresCheckpointPromotion =
        saveMode === "checkpoint" && lastSaveModeRef.current === "autosave";

      if (
        stableFingerprint === persistedFingerprintRef.current &&
        !requiresCheckpointPromotion &&
        effectiveLastSavedAt &&
        (effectiveVersionId || !stableResume)
      ) {
        setSaveState("saved");
        return {
          savedAt: effectiveLastSavedAt,
          versionId: effectiveVersionId,
        };
      }

      if (!stableResume || stableResume.id !== resumeId) {
        throw new Error("No active resume is available to save.");
      }

      const request = (async (): Promise<SaveResponse> => {
        setSaveState("saving");
        recentlySavedFingerprintsRef.current.clear();
        try {
          const saved = await saveResumeApi(
            stableResume.id,
            {
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
              console.error("Failed to refresh resume versions.", versionsError);
            }
          }

          return { savedAt: saved.savedAt, versionId: saved.versionId };
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
    [adoptPersistedSave, getSnapshot, resumeId],
  );

  const resolveAppliedAgentDraft = useCallback(
    async (
      messageId: string,
      candidateResume: ResumeData,
    ): Promise<AgentDraftDecisionResolution> => {
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
      }

      const resolutionPromise = (async () => {
        setSaveState("saving");
        try {
          const resolution = await resolveAgentDraftDecision(
            resumeId,
            messageId,
            { status: "applied", resume: candidateResume },
          );
          if (resolution.status === "applied" && resolution.resume) {
            adoptPersistedSave(
              resolution.resume,
              resolution.committed
                ? { ...resolution.resume.resume, resume: candidateResume }
                : resolution.resume.resume,
              "autosave",
            );
          } else {
            setSaveState("idle");
          }
          return resolution;
        } catch (error) {
          setSaveState("idle");
          throw error;
        }
      })();
      const trackedRequest: ActiveResumeSave = {
        promise: resolutionPromise.then((resolution) => ({
          savedAt: resolution.resume?.savedAt ?? lastSavedAtRef.current ?? "",
          versionId:
            resolution.resume?.versionId ?? activeVersionIdRef.current ?? undefined,
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
    [adoptPersistedSave, resumeId],
  );

  const discard = useCallback(async () => {
    const persistedResume = persistedResumeRef.current;
    if (!persistedResume) {
      return;
    }

    const activeRequest = activeRequestRef.current;
    const hasActiveSave = activeRequest?.resumeId === persistedResume.id;
    const shouldCheckpoint =
      hasActiveSave || lastSaveModeRef.current === "autosave";

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
        jobBrief: persistedResume.jobBrief,
        resume: persistedResume.resume,
        template: persistedResume.template,
        templateSettings: persistedResume.templateSettings ?? null,
        title: persistedResume.title,
        typography: persistedResume.typography,
      },
      "checkpoint",
    );
    persistedResumeRef.current = restored.resume;
    persistenceEpochRef.current += 1;
    setPersistedResume(restored.resume);
    persistedFingerprintRef.current = createResumeFingerprint(restored.resume);
    lastSaveModeRef.current = "checkpoint";
    skipCheckpointPromotionRef.current = false;
    lastSavedAtRef.current = restored.savedAt;
    activeVersionIdRef.current = restored.versionId;
    onHydrateResume(restored.resume);
    setLastSavedAt(restored.savedAt);
    setActiveVersionId(restored.versionId);
    setSaveState("saved");
  }, [onHydrateResume]);

  const selectVersion = useCallback(
    async (versionId: string) => {
      if (
        versionId === activeVersionIdRef.current ||
        versionLoadRequestRef.current ||
        saveState === "saving"
      ) {
        return;
      }

      versionLoadRequestRef.current = versionId;
      setIsVersionLoading(true);
      setHasVersionLoadError(false);
      try {
        const detail = await fetchResumeVersionApi(resumeId, versionId);
        onHydrateResume(detail.resume);
        hydratePersistedResume(detail, versions);
        persistenceEpochRef.current += 1;
      } catch (error) {
        console.error("Failed to load resume version.", error);
        setHasVersionLoadError(true);
        setSaveState("idle");
      } finally {
        versionLoadRequestRef.current = null;
        setIsVersionLoading(false);
      }
    },
    [hydratePersistedResume, onHydrateResume, resumeId, saveState, versions],
  );

  useEffect(() => {
    autosaveGenerationRef.current += 1;
    autosaveBurstStartedAtRef.current = null;
    autosaveRetryAttemptRef.current = 0;
    toast.dismiss("autosave-failed");
  }, [resumeId]);

  useEffect(() => {
    if (isLoading) {
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
    if (liveFingerprint === persistedFingerprintRef.current) {
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
    changeCount: countResumeChanges(
      persistedResume,
      liveResume,
    ),
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
      lastSaveModeRef.current === "autosave" &&
      !skipCheckpointPromotionRef.current,
    save,
    saveState,
    resolveAppliedAgentDraft,
    selectVersion,
    versions,
  };
}

export type ResumeDetailSaveController = ReturnType<
  typeof useResumeDetailSave
>;
