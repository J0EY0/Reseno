import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { isApiErrorToastShown } from "@/lib/api-client";
import {
  downloadExportedFile,
  downloadExportedPdf,
  downloadResumeJson,
  requestResumeImagesExport,
  requestResumePdfExport,
} from "@/lib/export-api";
import type { ResumeDetailResponse } from "@/types/api";
import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

interface ResumeDetailExportOptions {
  messages: AppMessages;
  save: () => Promise<ResumeDetailResponse>;
  templates: ResumeTemplateDefinition[];
}

/** Serializes exports and checkpoints the exact document they reference. */
export function useResumeDetailExport({
  messages,
  save,
  templates,
}: ResumeDetailExportOptions) {
  const exportInFlightRef = useRef(false);
  const [isExporting, setIsExporting] = useState(false);

  const runExport = useCallback(
    async (
      operation: (
        activeResume: ResumeWorkspaceItem,
        savedVersion: ResumeDetailResponse,
      ) => Promise<void> | void,
    ) => {
      if (exportInFlightRef.current) {
        return;
      }

      exportInFlightRef.current = true;
      setIsExporting(true);
      try {
        const savedVersion = await save();
        await operation(savedVersion.resume, savedVersion);
      } finally {
        exportInFlightRef.current = false;
        setIsExporting(false);
      }
    },
    [save],
  );

  const exportPdf = useCallback(async () => {
    try {
      await runExport(async (activeResume, savedVersion) => {
        const result = await requestResumePdfExport({
          fileNameSeed: activeResume.title,
          resumeId: activeResume.id,
          savedAt: savedVersion.savedAt,
          versionId: savedVersion.versionId,
        });
        await downloadExportedPdf(result);
        toast.success(messages.exportSuccess, { closeButton: true });
      });
    } catch (error) {
      console.error("Failed to export resume PDF.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.exportFailed, { closeButton: true });
      }
    }
  }, [messages.exportFailed, messages.exportSuccess, runExport]);

  const exportImages = useCallback(async () => {
    try {
      await runExport(async (activeResume, savedVersion) => {
        const result = await requestResumeImagesExport({
          fileNameSeed: activeResume.title,
          resumeId: activeResume.id,
          savedAt: savedVersion.savedAt,
          versionId: savedVersion.versionId,
        });
        await downloadExportedFile(result);
        toast.success(messages.exportImagesSuccess, { closeButton: true });
      });
    } catch (error) {
      console.error("Failed to export resume images.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.exportImagesFailed, { closeButton: true });
      }
    }
  }, [messages.exportImagesFailed, messages.exportImagesSuccess, runExport]);

  const exportJson = useCallback(async () => {
    try {
      await runExport((activeResume) => {
        const template = templates.find((item) => item.id === activeResume.template);
        if (!template) {
          throw new Error("The saved resume's template definition is unavailable.");
        }
        downloadResumeJson(activeResume, template);
        toast.success(messages.exportJsonSuccess, { closeButton: true });
      });
    } catch (error) {
      console.error("Failed to export resume JSON.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.exportJsonFailed, { closeButton: true });
      }
    }
  }, [messages.exportJsonFailed, messages.exportJsonSuccess, runExport, templates]);

  return { exportImages, exportJson, exportPdf, isExporting };
}
