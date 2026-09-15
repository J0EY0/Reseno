import { act, renderHook } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { defaultMessages } from "@/i18n";
import { notifyApiError } from "@/lib/api-error-notifier";
import { createEmptyResume } from "@/lib/resume";
import type { ResumeDetailResponse } from "@/types/api";

import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));
vi.mock("@/lib/api-error-notifier", () => ({ notifyApiError: vi.fn() }));

beforeEach(() => {
  vi.resetModules();
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => vi.doUnmock("@/lib/export-api"));

describe.each(["Pdf", "Images", "Json"] as const)(
  "%s export lifecycle",
  (format) => {
    it.each([null, "save", "import"] as const)(
      "serializes checkpoint and module loading across %s failure",
      async (failureMode) => {
        const calls: unknown[] = [];
        const errors: unknown[] = [];
        let moduleLoads = 0;
        let failImport = failureMode === "import";
        const savedVersion: ResumeDetailResponse = {
          resume: createResumeDetailItem({ resume: createEmptyResume() }),
          savedAt: "2026-09-01T00:00:00.000Z",
          versionId: "version-a",
        };
        const artifact = { downloadUrl: "/export", fileName: "resume" };
        let resolveSave!: (value: ResumeDetailResponse) => void;
        let rejectSave!: (error: Error) => void;
        const gate = new Promise<ResumeDetailResponse>((resolve, reject) => {
          resolveSave = resolve;
          rejectSave = reject;
        });
        const save = vi.fn(() => gate);
        vi.mocked(toast.success).mockImplementation(() => {
          calls.push("success");
          return "toast";
        });
        vi.mocked(notifyApiError).mockImplementation((error) => {
          errors.push(error);
          return true;
        });
        const exportApi = {
          requestResumePdfExport: vi.fn(async (input: unknown) => {
            calls.push(["request", input]);
            return artifact;
          }),
          requestResumeImagesExport: vi.fn(async (input: unknown) => {
            calls.push(["request", input]);
            return artifact;
          }),
          downloadExportedPdf: vi.fn(async (value: unknown) => {
            expect(value).toBe(artifact);
            calls.push("download");
          }),
          downloadExportedFile: vi.fn(async (value: unknown) => {
            expect(value).toBe(artifact);
            calls.push("download");
          }),
          downloadResumeJson: vi.fn((value: unknown) => {
            expect(value).toBe(savedVersion.resume);
            calls.push("download");
          }),
        };
        const loadExportApi = () => {
          moduleLoads += 1;
          if (failImport) throw new Error("Chunk unavailable");
          return exportApi;
        };
        vi.doMock("@/lib/export-api", loadExportApi);
        const { useResumeDetailExport } =
          await import("@/components/workspace/use-resume-detail-export");

        const template = createResumeDetailTemplate("minimal", {
          name: "Minimal",
          updatedAt: savedVersion.savedAt,
          isBuiltIn: true,
        });
        const { result } = renderHook(() =>
          useResumeDetailExport({
            messages: defaultMessages,
            templates: [template],
            save,
          }),
        );
        const method = `export${format}` as const;
        expect(moduleLoads).toBe(0);
        let exporting!: Promise<void>;
        act(() => {
          exporting = result.current[method]();
        });
        expect(result.current.isExporting).toBe(true);
        await act(async () => {
          await result.current[method]();
          await vi.dynamicImportSettled();
        });
        expect(save).toHaveBeenCalledTimes(1);
        expect(moduleLoads).toBe(1);
        expect(calls).toEqual([]);
        await act(async () => {
          if (failureMode === "save")
            rejectSave(new Error("Checkpoint failed"));
          else resolveSave(savedVersion);
          await exporting;
        });
        expect(result.current.isExporting).toBe(false);
        expect(errors).toHaveLength(failureMode ? 1 : 0);
        if (failureMode) {
          expect(calls).toEqual([]);
          failImport = false;
          if (failureMode === "import") {
            vi.resetModules();
            vi.doMock("@/lib/export-api", loadExportApi);
          }
          await act(async () => {
            await result.current[method]();
          });
          expect(save).toHaveBeenCalledTimes(2);
          expect(result.current.isExporting).toBe(false);
          if (failureMode === "save") {
            expect(calls).toEqual([]);
            expect(errors).toHaveLength(2);
            save.mockResolvedValue(savedVersion);
            await act(async () => {
              await result.current[method]();
            });
            expect(save).toHaveBeenCalledTimes(3);
            expect(result.current.isExporting).toBe(false);
            expect(errors).toHaveLength(2);
          }
        }
        expect(calls.at(-1)).toBe("success");
        expect(calls.at(-2)).toBe("download");
        if (format !== "Json")
          expect(calls[0]).toEqual([
            "request",
            {
              fileNameSeed: savedVersion.resume.title,
              resumeId: savedVersion.resume.id,
              savedAt: savedVersion.savedAt,
              versionId: savedVersion.versionId,
            },
          ]);
      },
    );
  },
);
