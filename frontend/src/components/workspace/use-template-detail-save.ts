import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";
import type { AppMessages } from "@/i18n";
import { useAuthSessionToken } from "@/hooks/use-auth-session-token";
import {
  countTemplateChanges,
  createTemplateFingerprint,
} from "@/lib/workspace-change-tracking";
import {
  discardTemplateChangesApi,
  saveTemplateApi,
} from "@/lib/workspace-api";
import { notifyApiError } from "@/lib/api-error-notifier";
import type {
  ApiRequestOptions,
  TemplateEditingResponse,
  TemplateSaveMode,
} from "@/types/api";
import type { ResumeTemplateDefinition } from "@/types/resume";

const AUTOSAVE_DELAY_MS = 5_000;
const AUTOSAVE_MAX_WAIT_MS = 30_000;
const AUTOSAVE_RETRY_DELAYS_MS = [2_000, 5_000] as const;
export type TemplateDetailSaveState = "idle" | "saving" | "saved";
interface TemplateSaveResult {
  savedAt: string;
  template: ResumeTemplateDefinition;
}
interface ActiveTemplateSave {
  mode: TemplateSaveMode | "discard";
  promise: Promise<TemplateSaveResult>;
}
interface PersistedTemplateState {
  checkpoint: ResumeTemplateDefinition | null;
  checkpointFingerprint: string;
  fingerprint: string;
  template: ResumeTemplateDefinition | null;
}
function createPersistedState(
  template: ResumeTemplateDefinition | null,
  checkpoint: ResumeTemplateDefinition | null,
): PersistedTemplateState {
  const fingerprint = createTemplateFingerprint(template);
  return {
    checkpoint,
    checkpointFingerprint: checkpoint
      ? createTemplateFingerprint(checkpoint)
      : fingerprint,
    fingerprint,
    template,
  };
}
interface TemplateDetailSaveOptions {
  initialCheckpoint: ResumeTemplateDefinition | null;
  isLoading: boolean;
  messages: AppMessages;
  onAdoptSavedTemplate: (
    template: ResumeTemplateDefinition,
    acceptedFingerprints: ReadonlySet<string>,
  ) => void;
  onRestoreTemplate: (template: ResumeTemplateDefinition) => void;
  template: ResumeTemplateDefinition | null;
}
export function useTemplateDetailSave({
  initialCheckpoint,
  isLoading,
  messages,
  onAdoptSavedTemplate,
  onRestoreTemplate,
  template,
}: TemplateDetailSaveOptions) {
  const authToken = useAuthSessionToken();
  const live = useMemo(
    () => ({ template, fingerprint: createTemplateFingerprint(template) }),
    [template],
  );
  const [persisted, setPersisted] = useState(() =>
    createPersistedState(template, initialCheckpoint),
  );
  const [saveState, setSaveState] = useState<TemplateDetailSaveState>("idle");
  const activeRequestRef = useRef<ActiveTemplateSave | null>(null);
  const persistedRef = useRef(persisted);
  const autosaveBurstStartedAtRef = useRef<number | null>(null);
  const autosaveGenerationRef = useRef(0);
  const autosaveRetryAttemptRef = useRef(0);
  const latestRef = useRef(live);
  const callbacksRef = useRef({ onAdoptSavedTemplate, onRestoreTemplate });
  useLayoutEffect(() => {
    latestRef.current = live;
  }, [live]);
  useLayoutEffect(() => {
    callbacksRef.current = { onAdoptSavedTemplate, onRestoreTemplate };
  }, [onAdoptSavedTemplate, onRestoreTemplate]);
  const hasUnpersistedChanges = useCallback(() => {
    const current = latestRef.current;
    return Boolean(
      current.template &&
      !current.template.isBuiltIn &&
      current.fingerprint !== persistedRef.current.fingerprint,
    );
  }, []);
  const hasUnsavedChanges = useCallback(() => {
    const current = latestRef.current;
    return Boolean(
      current.template &&
      !current.template.isBuiltIn &&
      (current.fingerprint !== persistedRef.current.checkpointFingerprint ||
        current.fingerprint !== persistedRef.current.fingerprint),
    );
  }, []);
  const updatePersisted = useCallback((next: PersistedTemplateState) => {
    persistedRef.current = next;
    setPersisted(next);
  }, []);
  const hydratePersistedTemplate = useCallback(
    (
      nextTemplate: ResumeTemplateDefinition,
      checkpoint: ResumeTemplateDefinition | null,
    ) => {
      autosaveGenerationRef.current += 1;
      updatePersisted(createPersistedState(nextTemplate, checkpoint));
      setSaveState("idle");
    },
    [updatePersisted],
  );
  const adoptResponse = useCallback(
    (response: TemplateEditingResponse, submittedFingerprint: string) => {
      const next = createPersistedState(response.template, response.checkpoint);
      const accepted = new Set([submittedFingerprint, next.fingerprint]);
      updatePersisted(next);
      if (
        latestRef.current.template?.id === response.template.id &&
        accepted.has(latestRef.current.fingerprint)
      )
        latestRef.current = {
          template: response.template,
          fingerprint: next.fingerprint,
        };
      callbacksRef.current.onAdoptSavedTemplate(response.template, accepted);
      setSaveState("saved");
      return {
        savedAt: response.template.updatedAt,
        template: response.template,
      };
    },
    [updatePersisted],
  );
  const persist = useCallback(
    async (
      mode: TemplateSaveMode,
      options: Pick<ApiRequestOptions, "notifyOnError"> = {},
    ): Promise<TemplateSaveResult> => {
      while (activeRequestRef.current) {
        const active = activeRequestRef.current;
        try {
          await active.promise;
        } catch {
          /* A queued save owns its retry. */
        } finally {
          if (activeRequestRef.current === active)
            activeRequestRef.current = null;
        }
      }
      const snapshot = latestRef.current;
      if (!snapshot.template)
        throw new Error("No template is available to save.");
      if (
        snapshot.template.isBuiltIn ||
        (snapshot.fingerprint === persistedRef.current.fingerprint &&
          (mode === "autosave" || persistedRef.current.checkpoint === null))
      ) {
        if (!snapshot.template.isBuiltIn) {
          setSaveState("saved");
        }
        return {
          savedAt: snapshot.template.updatedAt,
          template: snapshot.template,
        };
      }
      const submittedTemplate = snapshot.template;
      const request = (async () => {
        setSaveState("saving");
        try {
          return adoptResponse(
            await saveTemplateApi(submittedTemplate.id, submittedTemplate, {
              ...options,
              saveMode: mode,
            }),
            snapshot.fingerprint,
          );
        } catch (error) {
          setSaveState("idle");
          throw error;
        }
      })();
      const active = {
        mode,
        promise: request,
      };
      activeRequestRef.current = active;
      try {
        return await request;
      } finally {
        if (activeRequestRef.current === active)
          activeRequestRef.current = null;
      }
    },
    [adoptResponse],
  );
  const save = useCallback(
    (options: Pick<ApiRequestOptions, "notifyOnError"> = {}) =>
      persist("checkpoint", options),
    [persist],
  );
  const discard = useCallback(async () => {
    const state = persistedRef.current;
    const target = state.checkpoint ?? state.template;
    if (!target || target.isBuiltIn) return;
    autosaveGenerationRef.current += 1;
    const previous = activeRequestRef.current;
    const request = (async (): Promise<TemplateSaveResult> => {
      if (previous) {
        try {
          await previous.promise;
        } catch {
          /* The explicit checkpoint remains the discard target. */
        }
      }
      const response =
        previous?.mode === "checkpoint"
          ? await saveTemplateApi(target.id, target)
          : await discardTemplateChangesApi(target.id);
      const next = createPersistedState(response.template, response.checkpoint);
      updatePersisted(next);
      latestRef.current = {
        template: response.template,
        fingerprint: next.fingerprint,
      };
      callbacksRef.current.onRestoreTemplate(response.template);
      setSaveState("saved");
      return {
        savedAt: response.template.updatedAt,
        template: response.template,
      };
    })();
    const active: ActiveTemplateSave = {
      mode: "discard",
      promise: request,
    };
    activeRequestRef.current = active;
    try {
      await request;
    } finally {
      if (activeRequestRef.current === active) activeRequestRef.current = null;
    }
  }, [updatePersisted]);
  useEffect(() => {
    autosaveGenerationRef.current += 1;
    autosaveBurstStartedAtRef.current = null;
    autosaveRetryAttemptRef.current = 0;
    toast.dismiss("autosave-failed");
  }, [template?.id, authToken]);

  useEffect(() => {
    if (!authToken || isLoading || !template || template.isBuiltIn) {
      return;
    }

    if (live.fingerprint === persisted.fingerprint) {
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
        !hasUnpersistedChanges()
      ) {
        return;
      }

      try {
        await persist("autosave", { notifyOnError: false });
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
          !hasUnpersistedChanges()
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
        console.warn("Failed to autosave template after retries.", error);
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
    hasUnpersistedChanges,
    isLoading,
    messages.loadError,
    persist,
    live.fingerprint,
    persisted.fingerprint,
    template,
  ]);

  useEffect(() => {
    if (isLoading || saveState === "saving" || !hasUnpersistedChanges()) {
      return;
    }
    setSaveState("idle");
  }, [hasUnpersistedChanges, isLoading, saveState, template]);

  useEffect(() => {
    if (saveState !== "saved") {
      return;
    }
    const timer = window.setTimeout(() => setSaveState("idle"), 1_800);
    return () => window.clearTimeout(timer);
  }, [saveState]);

  const saveManually = useCallback(() => save().catch(notifyApiError), [save]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        !(event.metaKey || event.ctrlKey) ||
        event.key.toLowerCase() !== "s"
      ) {
        return;
      }
      event.preventDefault();
      if (!isLoading && template && !template.isBuiltIn) {
        saveManually();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isLoading, saveManually, template]);

  const changeCount = useMemo(
    () =>
      template && !template.isBuiltIn
        ? countTemplateChanges(
            persisted.checkpoint ?? persisted.template,
            template,
          )
        : 0,
    [persisted.checkpoint, persisted.template, template],
  );
  return {
    changeCount,
    discard,
    hasUnsavedChanges,
    hydratePersistedTemplate,
    lastSavedAt: persisted.template?.updatedAt ?? null,
    save,
    saveManually,
    saveState,
  };
}
