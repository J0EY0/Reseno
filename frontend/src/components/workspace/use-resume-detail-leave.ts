import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { isApiErrorToastShown } from "@/lib/api-client";

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
  const [pendingAction, setPendingAction] =
    useState<PendingLeaveAction | null>(null);
  const handledBlockedNavigationKeyRef = useRef<string | null>(null);
  const checkpointPromotionInFlightRef = useRef(false);

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
      if (checkpointPromotionInFlightRef.current) {
        return;
      }

      checkpointPromotionInFlightRef.current = true;
      void promoteCheckpoint()
        .then(() => {
          if (hasUnsavedChanges()) {
            setPendingAction({ cancel, run });
            return;
          }
          run();
        })
        .catch((error) => {
          console.warn(
            "Failed to checkpoint autosaved resume before leaving.",
            error,
          );
          if (hasUnsavedChanges()) {
            setPendingAction({ cancel, run });
            return;
          }

          // Autosave already owns the current content. A history-only failure
          // must not trap the user on this route.
          markCheckpointPromotionSkipped();
          toast.warning(messages.checkpointPromotionFailed, {
            closeButton: true,
            id: "checkpoint-promotion-failed",
          });
          run();
        })
        .finally(() => {
          checkpointPromotionInFlightRef.current = false;
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
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.loadError, { closeButton: true });
      }
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
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.loadError, { closeButton: true });
      }
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
