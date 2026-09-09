import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages } from "@/i18n";
import { notifyApiError } from "@/lib/api-error-notifier";
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
        exportApi: typeof import("@/lib/export-api"),
      ) => Promise<void> | void,
    ) => {
      if (exportInFlightRef.current) {
        return;
      }

      exportInFlightRef.current = true;
      setIsExporting(true);
      try {
        const [savedVersion, exportApi] = await Promise.all([
          save(),
          import("@/lib/export-api"),
        ]);
        await operation(savedVersion.resume, savedVersion, exportApi);
      } finally {
        exportInFlightRef.current = false;
        setIsExporting(false);
      }
    },
    [save],
  );

  const exportPdf = useCallback(async () => {
    try {
      await runExport(async (activeResume, savedVersion, exportApi) => {
        const result = await exportApi.requestResumePdfExport({
          fileNameSeed: activeResume.title,
          resumeId: activeResume.id,
          savedAt: savedVersion.savedAt,
          versionId: savedVersion.versionId,
        });
        await exportApi.downloadExportedPdf(result);
        toast.success(messages.exportSuccess, { closeButton: true });
      });
    } catch (error) {
      console.error("Failed to export resume PDF.", error);
      notifyApiError(error, messages.exportFailed);
    }
  }, [messages.exportFailed, messages.exportSuccess, runExport]);

  const exportImages = useCallback(async () => {
    try {
      await runExport(async (activeResume, savedVersion, exportApi) => {
        const result = await exportApi.requestResumeImagesExport({
          fileNameSeed: activeResume.title,
          resumeId: activeResume.id,
          savedAt: savedVersion.savedAt,
          versionId: savedVersion.versionId,
        });
        await exportApi.downloadExportedFile(result);
        toast.success(messages.exportImagesSuccess, { closeButton: true });
      });
    } catch (error) {
      console.error("Failed to export resume images.", error);
      notifyApiError(error, messages.exportImagesFailed);
    }
  }, [messages.exportImagesFailed, messages.exportImagesSuccess, runExport]);

  const exportJson = useCallback(async () => {
    try {
      await runExport((activeResume, _savedVersion, exportApi) => {
        const template = templates.find(
          (item) => item.id === activeResume.template,
        );
        if (!template) {
          throw new Error(
            "The saved resume's template definition is unavailable.",
          );
        }
        exportApi.downloadResumeJson(activeResume, template);
        toast.success(messages.exportJsonSuccess, { closeButton: true });
      });
    } catch (error) {
      console.error("Failed to export resume JSON.", error);
      notifyApiError(error, messages.exportJsonFailed);
    }
  }, [
    messages.exportJsonFailed,
    messages.exportJsonSuccess,
    runExport,
    templates,
  ]);

  return { exportImages, exportJson, exportPdf, isExporting };
}
