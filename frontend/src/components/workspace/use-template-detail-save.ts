import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import {
  countTemplateChanges,
  createTemplateFingerprint,
} from "@/lib/workspace-change-tracking";
import { saveTemplateApi } from "@/lib/workspace-api";
import type { ApiRequestOptions } from "@/types/api";
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
  promise: Promise<TemplateSaveResult>;
  templateId: string;
}

interface TemplateDetailSaveOptions {
  isLoading: boolean;
  messages: AppMessages;
  onAdoptSavedTemplate: (
    template: ResumeTemplateDefinition,
    acceptedFingerprints: ReadonlySet<string>,
  ) => void;
  onRestoreTemplate: (template: ResumeTemplateDefinition) => void;
  template: ResumeTemplateDefinition | null;
}

/** Owns the custom-template persistence transaction and its autosave policy. */
export function useTemplateDetailSave({
  isLoading,
  messages,
  onAdoptSavedTemplate,
  onRestoreTemplate,
  template,
}: TemplateDetailSaveOptions) {
  const initialPersistedTemplate =
    template && !template.isBuiltIn ? template : null;
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(
    template?.updatedAt || null,
  );
  const [saveState, setSaveState] =
    useState<TemplateDetailSaveState>("idle");
  const activeRequestRef = useRef<ActiveTemplateSave | null>(null);
  const lastSavedAtRef = useRef(lastSavedAt);
  const autosaveBurstStartedAtRef = useRef<number | null>(null);
  const autosaveGenerationRef = useRef(0);
  const autosaveRetryAttemptRef = useRef(0);
  const latestTemplateRef = useRef(template);
  const onAdoptSavedTemplateRef = useRef(onAdoptSavedTemplate);
  const onRestoreTemplateRef = useRef(onRestoreTemplate);
  const persistedFingerprintRef = useRef(
    createTemplateFingerprint(initialPersistedTemplate),
  );
  const persistedTemplateRef = useRef<ResumeTemplateDefinition | null>(
    initialPersistedTemplate,
  );

  latestTemplateRef.current = template;
  onAdoptSavedTemplateRef.current = onAdoptSavedTemplate;
  onRestoreTemplateRef.current = onRestoreTemplate;

  const hasUnsavedChanges = useCallback(() => {
    const current = latestTemplateRef.current;

    return Boolean(
      current &&
        !current.isBuiltIn &&
        createTemplateFingerprint(current) !== persistedFingerprintRef.current,
    );
  }, []);

  const hydratePersistedTemplate = useCallback(
    (nextTemplate: ResumeTemplateDefinition) => {
      const persisted = nextTemplate.isBuiltIn ? null : nextTemplate;

      autosaveGenerationRef.current += 1;
      persistedTemplateRef.current = persisted;
      persistedFingerprintRef.current = createTemplateFingerprint(persisted);
      lastSavedAtRef.current = nextTemplate.updatedAt || null;
      setLastSavedAt(lastSavedAtRef.current);
      setSaveState("idle");
    },
    [],
  );

  const adoptPersistedTemplate = useCallback(
    (nextTemplate: ResumeTemplateDefinition) => {
      const fingerprint = createTemplateFingerprint(nextTemplate);

      persistedTemplateRef.current = nextTemplate;
      persistedFingerprintRef.current = fingerprint;
      lastSavedAtRef.current = nextTemplate.updatedAt || null;
      setLastSavedAt(lastSavedAtRef.current);
      setSaveState("saved");
      onAdoptSavedTemplateRef.current(
        nextTemplate,
        new Set([fingerprint]),
      );
    },
    [],
  );

  const save = useCallback(
    async (
      options: Pick<ApiRequestOptions, "notifyOnError"> = {},
    ): Promise<TemplateSaveResult> => {
      while (activeRequestRef.current) {
        const activeRequest = activeRequestRef.current;

        try {
          await activeRequest.promise;
        } catch {
          // A queued save is a new intent and must retry the latest snapshot.
        } finally {
          if (activeRequestRef.current === activeRequest) {
            activeRequestRef.current = null;
          }
        }
      }

      const snapshot = latestTemplateRef.current;
      if (!snapshot) {
        throw new Error("No template is available to save.");
      }
      if (snapshot.isBuiltIn) {
        return { savedAt: snapshot.updatedAt, template: snapshot };
      }

      const submittedFingerprint = createTemplateFingerprint(snapshot);
      if (
        submittedFingerprint === persistedFingerprintRef.current &&
        lastSavedAtRef.current
      ) {
        setSaveState("saved");
        return { savedAt: lastSavedAtRef.current, template: snapshot };
      }

      const request = (async (): Promise<TemplateSaveResult> => {
        setSaveState("saving");

        try {
          const response = await saveTemplateApi(
            snapshot.id,
            snapshot,
            options,
          );
          const savedTemplate = response.template;
          const savedFingerprint = createTemplateFingerprint(savedTemplate);
          const savedAt =
            savedTemplate.updatedAt || new Date().toISOString();
          const acceptedFingerprints = new Set([
            submittedFingerprint,
            savedFingerprint,
          ]);

          persistedTemplateRef.current = savedTemplate;
          persistedFingerprintRef.current = savedFingerprint;
          onAdoptSavedTemplateRef.current(
            savedTemplate,
            acceptedFingerprints,
          );
          if (latestTemplateRef.current?.id === savedTemplate.id) {
            lastSavedAtRef.current = savedAt;
            setLastSavedAt(lastSavedAtRef.current);
            setSaveState("saved");
          }

          return {
            savedAt,
            template: savedTemplate,
          };
        } catch (error) {
          setSaveState("idle");
          throw error;
        }
      })();
      const trackedRequest = { promise: request, templateId: snapshot.id };
      activeRequestRef.current = trackedRequest;

      try {
        return await request;
      } finally {
        if (activeRequestRef.current === trackedRequest) {
          activeRequestRef.current = null;
        }
      }
    },
    [],
  );

  const discard = useCallback(async () => {
    const persistedTemplate = persistedTemplateRef.current;
    if (!persistedTemplate) {
      return;
    }

    const activeRequest = activeRequestRef.current;
    const hasActiveSave =
      activeRequest?.templateId === persistedTemplate.id;

    autosaveGenerationRef.current += 1;
    onRestoreTemplateRef.current(persistedTemplate);
    setSaveState("saved");

    if (!hasActiveSave) {
      return;
    }

    try {
      await activeRequest.promise;
    } catch {
      // The captured persisted snapshot below remains the discard source of truth.
    }

    const response = await saveTemplateApi(
      persistedTemplate.id,
      persistedTemplate,
    );
    adoptPersistedTemplate(response.template);
  }, [adoptPersistedTemplate]);

  useEffect(() => {
    autosaveGenerationRef.current += 1;
    autosaveBurstStartedAtRef.current = null;
    autosaveRetryAttemptRef.current = 0;
    toast.dismiss("autosave-failed");
  }, [template?.id]);

  useEffect(() => {
    if (isLoading || !template || template.isBuiltIn) {
      return;
    }

    const activeFingerprint = createTemplateFingerprint(template);
    if (activeFingerprint === persistedFingerprintRef.current) {
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
        await save({ notifyOnError: false });
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
  }, [hasUnsavedChanges, isLoading, messages.loadError, save, template]);

  useEffect(() => {
    if (isLoading || saveState === "saving" || !hasUnsavedChanges()) {
      return;
    }
    setSaveState("idle");
  }, [hasUnsavedChanges, isLoading, saveState, template]);

  useEffect(() => {
    if (saveState !== "saved") {
      return;
    }
    const timer = window.setTimeout(() => setSaveState("idle"), 1_800);
    return () => window.clearTimeout(timer);
  }, [saveState]);

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
        void save();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isLoading, save, template]);

  return {
    adoptPersistedTemplate,
    changeCount:
      template && !template.isBuiltIn
        ? countTemplateChanges(persistedTemplateRef.current, template)
        : 0,
    discard,
    hasUnsavedChanges,
    hydratePersistedTemplate,
    lastSavedAt,
    save,
    saveState,
  };
}
