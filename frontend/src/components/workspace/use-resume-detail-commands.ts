import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { toast } from "sonner";

import type { DocumentCanvasHandle } from "@/components/preview/document-canvas";
import type { ResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import type { ResumeDetailSaveController } from "@/components/workspace/use-resume-detail-save";
import type { AppMessages } from "@/i18n";
import { getRichTextPlainText } from "@/lib/rich-text";
import { isAbortError } from "@/lib/api-client";
import { notifyApiError } from "@/lib/api-error-notifier";
import {
  createDefaultResumeTitle,
  normalizeResumeTitle,
  truncateResumeTitle,
} from "@/lib/resume-title";
import type { SmartOnePageStyleSnapshot } from "@/lib/smart-one-page";
import { createTemplateSettings } from "@/lib/templates";
import { duplicateResumeApi } from "@/lib/workspace-api";
import type { ResumeDetailResponse } from "@/types/api";
import type {
  ResumeData,
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
} from "@/types/resume";

interface ResumeDetailCommandsOptions {
  activeTemplate: ResumeTemplateDefinition;
  isLoading: boolean;
  messages: AppMessages;
  navigateToResume: (detail: ResumeDetailResponse) => void;
  previewResume: ResumeData;
  resumeOrdinal: number;
  save: Pick<
    ResumeDetailSaveController,
    "hasUnsavedChanges" | "save" | "saveState"
  >;
  session: Pick<
    ResumeDetailSession,
    | "applyTemplate"
    | "document"
    | "fingerprint"
    | "rename"
    | "resume"
    | "template"
    | "templateSettings"
    | "typography"
    | "updateStyle"
  >;
  templateCatalog: ResumeTemplateDefinition[];
}

/** Owns editor commands that do not belong to transport or page layout. */
export function useResumeDetailCommands({
  activeTemplate,
  isLoading,
  messages,
  navigateToResume,
  previewResume,
  resumeOrdinal,
  save,
  session,
  templateCatalog,
}: ResumeDetailCommandsOptions) {
  const duplicateInFlightRef = useRef(false);
  const documentPreviewRef = useRef<DocumentCanvasHandle | null>(null);
  const [isDuplicating, setIsDuplicating] = useState(false);
  const [isSmartFitting, setIsSmartFitting] = useState(false);
  const [candidateStyle, setCandidateStyle] =
    useState<SmartOnePageStyleSnapshot | null>(null);
  const fittingRef = useRef<{
    controller: AbortController;
    fingerprint: string;
    resume: ResumeData;
  } | null>(null);
  const latestSessionRef = useRef(session);
  const [isPreviewReady, setIsPreviewReady] = useState(false);
  const [isTitleDialogOpen, setIsTitleDialogOpen] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  useLayoutEffect(() => {
    latestSessionRef.current = session;
    const fitting = fittingRef.current;
    if (
      fitting &&
      (fitting.fingerprint !== session.fingerprint ||
        fitting.resume !== previewResume)
    ) {
      fitting.controller.abort();
    }
  }, [previewResume, session]);
  useEffect(() => () => fittingRef.current?.controller.abort(), []);
  const previewStyle =
    fittingRef.current &&
    fittingRef.current.fingerprint === session.fingerprint &&
    fittingRef.current.resume === previewResume
      ? candidateStyle
      : null;

  const setTitleDialogOpen = useCallback(
    (open: boolean) => {
      setIsTitleDialogOpen(open);
      if (open) {
        setTitleDraft(session.document?.title || messages.untitledResume);
      }
    },
    [messages.untitledResume, session.document?.title],
  );

  const changeTitleDraft = useCallback((value: string) => {
    setTitleDraft(truncateResumeTitle(value));
  }, []);

  const saveTitle = useCallback(() => {
    const fallbackTitle =
      getRichTextPlainText(session.resume.basic.name) ||
      createDefaultResumeTitle(messages, resumeOrdinal) ||
      messages.untitledResume;
    session.rename(normalizeResumeTitle(titleDraft, fallbackTitle));
    setIsTitleDialogOpen(false);
  }, [messages, resumeOrdinal, session, titleDraft]);

  const applyTemplate = useCallback(
    (templateId: string) => {
      const target = templateCatalog.find((item) => item.id === templateId);
      if (!target) {
        return;
      }
      if (
        templateId === session.template &&
        target.typography.fontFamily === session.typography.fontFamily &&
        target.typography.fontSize === session.typography.fontSize
      ) {
        return;
      }
      session.applyTemplate(target);
    },
    [session, templateCatalog],
  );

  const restoreTemplateDefaults = useCallback(() => {
    // Null makes the selected template the single source of layout defaults.
    session.updateStyle({
      typography: { ...activeTemplate.typography },
      templateSettings: null,
    });
  }, [activeTemplate.typography, session]);

  const updateTemplateSettings = useCallback(
    (patch: Partial<ResumeTemplateSettings>) => {
      session.updateStyle((current) => ({
        templateSettings: createTemplateSettings(activeTemplate.preset, {
          ...activeTemplate.settings,
          ...(current.templateSettings ?? {}),
          ...patch,
        }),
      }));
    },
    [activeTemplate, session],
  );

  const fitOnePage = useCallback(async () => {
    const previewHandle = documentPreviewRef.current;
    if (!isPreviewReady || fittingRef.current || !previewHandle) {
      return;
    }

    setIsSmartFitting(true);
    const controller = new AbortController();
    let measurementKey: object | undefined;
    fittingRef.current = {
      controller,
      fingerprint: session.fingerprint,
      resume: previewResume,
    };
    const previous = {
      templateSettings: session.templateSettings,
      typography: session.typography,
    };
    const effectiveSettings = createTemplateSettings(activeTemplate.preset, {
      ...activeTemplate.settings,
      ...(session.templateSettings ?? {}),
    });
    try {
      const { fitResumeToOnePage } = await import("@/lib/smart-one-page");
      controller.signal.throwIfAborted();
      const result = await fitResumeToOnePage(previous, effectiveSettings, {
        applyStyle(snapshot) {
          controller.signal.throwIfAborted();
          measurementKey = snapshot;
          setCandidateStyle(snapshot);
        },
        measurePageCount: () =>
          previewHandle.measurePageCount(controller.signal, measurementKey),
      });
      controller.signal.throwIfAborted();
      if (result.status === "already-one-page") {
        toast.info(messages.smartOnePageAlready, { duration: 1_800 });
      } else if (result.status === "applied") {
        session.updateStyle(result.style);
        toast.success(messages.smartOnePageApplied, {
          action: {
            label: messages.undoAction,
            onClick: () => {
              const latest = latestSessionRef.current;
              if (
                latest.typography !== result.style.typography ||
                latest.templateSettings !== result.style.templateSettings
              ) {
                return;
              }
              session.updateStyle(result.previous);
            },
          },
          duration: 6_000,
        });
      } else {
        toast.info(messages.smartOnePageNoChange, { duration: 1_800 });
      }
    } catch (error) {
      if (!isAbortError(error)) {
        console.error("Failed to fit resume to one page.", error);
        toast.error(messages.loadError, { closeButton: true });
      }
    } finally {
      fittingRef.current = null;
      setCandidateStyle(null);
      setIsSmartFitting(false);
    }
  }, [activeTemplate, isPreviewReady, messages, previewResume, session]);

  const duplicate = useCallback(async () => {
    if (
      !session.document ||
      isLoading ||
      save.saveState === "saving" ||
      duplicateInFlightRef.current
    ) {
      return;
    }

    duplicateInFlightRef.current = true;
    setIsDuplicating(true);
    try {
      await save.save();
      if (save.hasUnsavedChanges()) {
        toast.warning(messages.duplicateResumeChangedDuringSave, {
          closeButton: true,
        });
        return;
      }

      const detail = await duplicateResumeApi(session.document.id);
      toast.success(messages.resumeDuplicated, {
        action: {
          label: messages.viewDuplicateResume,
          onClick: () => navigateToResume(detail),
        },
        classNames: {
          content: "min-w-0! flex-1!",
          description: "truncate! opacity-75!",
        },
        closeButton: true,
        description: detail.resume.title,
        duration: 6_000,
        icon: null,
      });
    } catch (error) {
      console.error("Failed to duplicate resume.", error);
      notifyApiError(error, messages.duplicateResumeFailed);
    } finally {
      duplicateInFlightRef.current = false;
      setIsDuplicating(false);
    }
  }, [isLoading, messages, navigateToResume, save, session.document]);

  return {
    applyTemplate,
    changeTitleDraft,
    documentPreviewRef:
      documentPreviewRef as RefObject<DocumentCanvasHandle | null>,
    duplicate,
    fitOnePage,
    isDuplicating,
    isPreviewReady,
    isSmartFitting,
    isTitleDialogOpen,
    previewStyle,
    restoreTemplateDefaults,
    saveTitle,
    setPreviewReady: setIsPreviewReady,
    setTitleDialogOpen,
    titleDraft,
    updateTemplateSettings,
  };
}
