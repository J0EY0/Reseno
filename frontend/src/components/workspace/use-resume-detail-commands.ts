import { useCallback, useRef, useState, type RefObject } from "react";
import { toast } from "sonner";

import type { DocumentPreviewHandle } from "@/components/preview/document-preview-card";
import type { ResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import type { ResumeDetailSaveController } from "@/components/workspace/use-resume-detail-save";
import type { AppMessages, Locale } from "@/i18n";
import { isApiErrorToastShown } from "@/lib/api-client";
import {
  createDefaultResumeTitle,
  normalizeResumeTitle,
  truncateResumeTitle,
} from "@/lib/resume-title";
import { fitResumeToOnePage } from "@/lib/smart-one-page";
import { createTemplateSettings } from "@/lib/templates";
import { duplicateResumeApi } from "@/lib/workspace-api";
import type { ResumeDetailResponse } from "@/types/api";
import type {
  ResumeTemplateDefinition,
  ResumeTemplateSettings,
} from "@/types/resume";

interface ResumeDetailCommandsOptions {
  activeTemplate: ResumeTemplateDefinition;
  isLoading: boolean;
  locale: Locale;
  messages: AppMessages;
  navigateToResume: (detail: ResumeDetailResponse) => void;
  resumeOrdinal: number;
  save: ResumeDetailSaveController;
  session: ResumeDetailSession;
  templateCatalog: ResumeTemplateDefinition[];
}

/** Owns editor commands that do not belong to transport or page layout. */
export function useResumeDetailCommands({
  activeTemplate,
  isLoading,
  locale,
  messages,
  navigateToResume,
  resumeOrdinal,
  save,
  session,
  templateCatalog,
}: ResumeDetailCommandsOptions) {
  const duplicateInFlightRef = useRef(false);
  const documentPreviewRef = useRef<DocumentPreviewHandle | null>(null);
  const [isDuplicating, setIsDuplicating] = useState(false);
  const [isSmartFitting, setIsSmartFitting] = useState(false);
  const [isPreviewReady, setIsPreviewReady] = useState(false);
  const [isTitleDialogOpen, setIsTitleDialogOpen] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const setTitleDialogOpen = useCallback(
    (open: boolean) => {
      setIsTitleDialogOpen(open);
      if (open) {
        setTitleDraft(session.resumeItem?.title || messages.untitledResume);
      }
    },
    [messages.untitledResume, session.resumeItem?.title],
  );

  const changeTitleDraft = useCallback((value: string) => {
    setTitleDraft(truncateResumeTitle(value));
  }, []);

  const saveTitle = useCallback(() => {
    session.setResumeItem((current) => {
      if (!current) {
        return current;
      }
      const fallbackTitle =
        session.resume.basic.name ||
        createDefaultResumeTitle(messages, resumeOrdinal) ||
        messages.untitledResume;
      const nextTitle = normalizeResumeTitle(titleDraft, fallbackTitle);

      return nextTitle === current.title
        ? current
        : { ...current, title: nextTitle, updatedAt: new Date().toISOString() };
    });
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
      session.setTemplate(templateId);
      session.setTypography(target.typography);
      session.setTemplateSettings(target.settings);
    },
    [session, templateCatalog],
  );

  const restoreTemplateDefaults = useCallback(() => {
    session.setTypography({ ...activeTemplate.typography });
    // Null makes the selected template the single source of layout defaults.
    session.setTemplateSettings(null);
  }, [activeTemplate.typography, session]);

  const updateTemplateSettings = useCallback(
    (patch: Partial<ResumeTemplateSettings>) => {
      session.setTemplateSettings((current) =>
        createTemplateSettings(activeTemplate.preset, {
          ...activeTemplate.settings,
          ...(current ?? {}),
          ...patch,
        }),
      );
    },
    [activeTemplate, session],
  );

  const fitOnePage = useCallback(async () => {
    const previewHandle = documentPreviewRef.current;
    if (!isPreviewReady || isSmartFitting || !previewHandle) {
      return;
    }

    setIsSmartFitting(true);
    const previous = {
      templateSettings: session.templateSettings,
      typography: session.typography,
    };
    const effectiveSettings = createTemplateSettings(activeTemplate.preset, {
      ...activeTemplate.settings,
      ...(session.templateSettings ?? {}),
    });
    try {
      const result = await fitResumeToOnePage(previous, effectiveSettings, {
        applyStyle(snapshot) {
          session.setTypography(snapshot.typography);
          session.setTemplateSettings(snapshot.templateSettings);
        },
        measurePageCount: () => previewHandle.measurePageCount(),
      });
      if (result.status === "already-one-page") {
        toast.info(messages.smartOnePageAlready, { duration: 1_800 });
      } else if (result.status === "applied") {
        toast.success(messages.smartOnePageApplied, {
          action: {
            label: messages.undoAction,
            onClick: () => {
              session.setTypography(result.previous.typography);
              session.setTemplateSettings(result.previous.templateSettings);
            },
          },
          duration: 2_600,
        });
      } else {
        toast.info(messages.smartOnePageNoChange, { duration: 1_800 });
      }
    } finally {
      setIsSmartFitting(false);
    }
  }, [activeTemplate, isPreviewReady, isSmartFitting, messages, session]);

  const duplicate = useCallback(async () => {
    if (
      !session.resumeItem ||
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

      const detail = await duplicateResumeApi(session.resumeItem.id, locale);
      toast.success(messages.resumeDuplicated, {
        action: {
          label: messages.viewDuplicateResume,
          onClick: () => navigateToResume(detail),
        },
        classNames: {
          actionButton:
            "h-8! rounded-md! border! border-current/20! bg-transparent! px-2.5! text-current! shadow-none! transition-colors! duration-200! hover:border-current/35! hover:bg-current/10! focus-visible:ring-2! focus-visible:ring-current! focus-visible:ring-offset-1!",
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
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.duplicateResumeFailed, { closeButton: true });
      }
    } finally {
      duplicateInFlightRef.current = false;
      setIsDuplicating(false);
    }
  }, [isLoading, locale, messages, navigateToResume, save, session.resumeItem]);

  return {
    applyTemplate,
    changeTitleDraft,
    documentPreviewRef: documentPreviewRef as RefObject<DocumentPreviewHandle | null>,
    duplicate,
    fitOnePage,
    isDuplicating,
    isPreviewReady,
    isSmartFitting,
    isTitleDialogOpen,
    restoreTemplateDefaults,
    saveTitle,
    setPreviewReady: setIsPreviewReady,
    setTitleDialogOpen,
    titleDraft,
    updateTemplateSettings,
  };
}
