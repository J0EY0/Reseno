import { useCallback, useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";

import type { AppMessages } from "@/i18n";
import { notifyApiError } from "@/lib/api-error-notifier";

interface PendingLeaveAction {
  cancel?: () => void;
  run: () => void;
}

interface TemplateDetailLeaveOptions {
  discard: () => Promise<void>;
  hasUnsavedChanges: () => boolean;
  messages: AppMessages;
  save: () => Promise<unknown>;
}

/** Owns in-app, history, logout, and browser-close protection for the draft. */
export function useTemplateDetailLeave({
  discard,
  hasUnsavedChanges,
  messages,
  save,
}: TemplateDetailLeaveOptions) {
  const [isResolving, setIsResolving] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingLeaveAction | null>(
    null,
  );
  const handledBlockedNavigationKeyRef = useRef<string | null>(null);

  const requestLeave = useCallback(
    (run: () => void, cancel?: () => void) => {
      if (!hasUnsavedChanges()) {
        run();
        return;
      }
      setPendingAction({ cancel, run });
    },
    [hasUnsavedChanges],
  );

  const navigationBlocker = useBlocker(hasUnsavedChanges);

  useEffect(() => {
    if (navigationBlocker.state !== "blocked") {
      handledBlockedNavigationKeyRef.current = null;
      return;
    }

    const blockedLocationKey = navigationBlocker.location.key;
    if (handledBlockedNavigationKeyRef.current === blockedLocationKey) {
      return;
    }

    handledBlockedNavigationKeyRef.current = blockedLocationKey;
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
      console.error("Failed to save the template before leaving.", error);
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
      console.error("Failed to discard template changes safely.", error);
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
