import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { notifyApiError } from "@/lib/api-error-notifier";

interface PendingLeaveAction {
  cancel?: () => void;
  run: () => void;
}

interface ResumeDetailLeaveOptions {
  discard: () => Promise<void>;
  hasUnsavedChanges: () => boolean;
  markCheckpointPromotionSkipped: () => void;
  messages: AppMessages;
  promoteCheckpoint: () => Promise<unknown>;
  requiresCheckpointPromotion: () => boolean;
  save: () => Promise<unknown>;
}

/** Protects the document while preserving autosave-to-history promotion. */
export function useResumeDetailLeave({
  discard,
  hasUnsavedChanges,
  markCheckpointPromotionSkipped,
  messages,
  promoteCheckpoint,
  requiresCheckpointPromotion,
  save,
}: ResumeDetailLeaveOptions) {
  const [isResolving, setIsResolving] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingLeaveAction | null>(
    null,
  );
  const handledBlockedNavigationKeyRef = useRef<string | null>(null);
  const checkpointPromotionInFlightRef = useRef<Promise<void> | null>(null);

  const requestLeave = useCallback(
    (run: () => void, cancel?: () => void) => {
      if (hasUnsavedChanges()) {
        setPendingAction({ cancel, run });
        return;
      }

      if (!requiresCheckpointPromotion()) {
        run();
        return;
      }

      const promotion =
        checkpointPromotionInFlightRef.current ??
        promoteCheckpoint()
          .then(() => undefined)
          .catch((error) => {
            console.warn(
              "Failed to checkpoint autosaved resume before leaving.",
              error,
            );

            // Autosave already owns the current content. A history-only
            // failure must not trap this or a newer navigation request.
            markCheckpointPromotionSkipped();
            toast.warning(messages.checkpointPromotionFailed, {
              closeButton: true,
              id: "checkpoint-promotion-failed",
            });
          });

      if (!checkpointPromotionInFlightRef.current) {
        checkpointPromotionInFlightRef.current = promotion;
        void promotion.finally(() => {
          if (checkpointPromotionInFlightRef.current === promotion) {
            checkpointPromotionInFlightRef.current = null;
          }
        });
      }

      void promotion.then(() => {
        if (hasUnsavedChanges()) {
          setPendingAction({ cancel, run });
          return;
        }
        run();
      });
    },
    [
      hasUnsavedChanges,
      markCheckpointPromotionSkipped,
      messages.checkpointPromotionFailed,
      promoteCheckpoint,
      requiresCheckpointPromotion,
    ],
  );

  const shouldBlockNavigation = useCallback(
    () => hasUnsavedChanges() || requiresCheckpointPromotion(),
    [hasUnsavedChanges, requiresCheckpointPromotion],
  );
  const navigationBlocker = useBlocker(shouldBlockNavigation);

  useEffect(() => {
    if (navigationBlocker.state !== "blocked") {
      handledBlockedNavigationKeyRef.current = null;
      return;
    }

    const locationKey = navigationBlocker.location.key;
    if (handledBlockedNavigationKeyRef.current === locationKey) {
      return;
    }
    handledBlockedNavigationKeyRef.current = locationKey;
    requestLeave(
      () => {
        handledBlockedNavigationKeyRef.current = null;
        navigationBlocker.proceed();
      },
      () => {
        handledBlockedNavigationKeyRef.current = null;
        navigationBlocker.reset();
      },
    );
  }, [navigationBlocker, requestLeave]);

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedChanges()) {
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasUnsavedChanges]);

  const cancelLeave = useCallback(() => {
    pendingAction?.cancel?.();
    setPendingAction(null);
  }, [pendingAction]);

  const saveAndLeave = useCallback(async () => {
    if (!pendingAction || isResolving) {
      return;
    }
    const action = pendingAction.run;
    setIsResolving(true);
    try {
      await save();
      setPendingAction(null);
      action();
    } catch (error) {
      console.error("Failed to save the resume before leaving.", error);
      notifyApiError(error, messages.loadError);
    } finally {
      setIsResolving(false);
    }
  }, [isResolving, messages.loadError, pendingAction, save]);

  const discardAndLeave = useCallback(async () => {
    if (!pendingAction || isResolving) {
      return;
    }
    const action = pendingAction.run;
    setIsResolving(true);
    try {
      await discard();
      setPendingAction(null);
      action();
    } catch (error) {
      console.error("Failed to discard resume changes safely.", error);
      notifyApiError(error, messages.loadError);
    } finally {
      setIsResolving(false);
    }
  }, [discard, isResolving, messages.loadError, pendingAction]);

  return {
    cancelLeave,
    discardAndLeave,
    isOpen: Boolean(pendingAction),
    isResolving,
    requestLeave,
    saveAndLeave,
  };
}
