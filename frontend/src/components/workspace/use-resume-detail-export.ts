import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import type { AppMessages, Locale } from "@/i18n";
import { isApiErrorToastShown } from "@/lib/api-client";
import {
  downloadExportedFile,
  downloadExportedPdf,
  downloadResumeJson,
  requestResumeImagesExport,
  requestResumePdfExport,
} from "@/lib/export-api";
import type { SaveResponse } from "@/types/api";
import type {
  ResumeTemplateDefinition,
  ResumeWorkspaceItem,
} from "@/types/resume";

interface ResumeDetailExportOptions {
  getSnapshot: (updatedAt: string) => ResumeWorkspaceItem | null;
  locale: Locale;
  messages: AppMessages;
  save: () => Promise<SaveResponse>;
  template: ResumeTemplateDefinition;
}

/** Serializes exports and checkpoints the exact document they reference. */
export function useResumeDetailExport({
  getSnapshot,
  locale,
  messages,
  save,
  template,
}: ResumeDetailExportOptions) {
  const exportInFlightRef = useRef(false);
  const [isExporting, setIsExporting] = useState(false);

  const runExport = useCallback(
    async (
      kind: "pdf" | "images" | "json",
      operation: (
        activeResume: ResumeWorkspaceItem,
        savedVersion: SaveResponse,
      ) => Promise<void> | void,
    ) => {
      if (exportInFlightRef.current) {
        return;
      }

      exportInFlightRef.current = true;
      setIsExporting(true);
      try {
        const savedVersion = await save();
        const activeResume = getSnapshot(savedVersion.savedAt);
        if (!activeResume) {
          throw new Error(`No active resume is available for ${kind} export.`);
        }
        await operation(activeResume, savedVersion);
      } finally {
        exportInFlightRef.current = false;
        setIsExporting(false);
      }
    },
    [getSnapshot, save],
  );

  const exportPdf = useCallback(async () => {
    try {
      await runExport("pdf", async (activeResume, savedVersion) => {
        const result = await requestResumePdfExport({
          fileNameSeed: activeResume.title,
          locale,
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
  }, [locale, messages.exportFailed, messages.exportSuccess, runExport]);

  const exportImages = useCallback(async () => {
    try {
      await runExport("images", async (activeResume, savedVersion) => {
        const result = await requestResumeImagesExport({
          fileNameSeed: activeResume.title,
          locale,
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
  }, [locale, messages.exportImagesFailed, messages.exportImagesSuccess, runExport]);

  const exportJson = useCallback(async () => {
    try {
      await runExport("json", (activeResume) => {
        downloadResumeJson(activeResume, template);
        toast.success(messages.exportJsonSuccess, { closeButton: true });
      });
    } catch (error) {
      console.error("Failed to export resume JSON.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(messages.exportJsonFailed, { closeButton: true });
      }
    }
  }, [messages.exportJsonFailed, messages.exportJsonSuccess, runExport, template]);

  return { exportImages, exportJson, exportPdf, isExporting };
}
