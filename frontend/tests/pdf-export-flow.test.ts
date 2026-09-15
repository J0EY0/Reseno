import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useResumeDetailExport } from "@/components/workspace/use-resume-detail-export";
import { clearApiCache } from "@/lib/api-client";
import { saveAuthSession } from "@/lib/auth-session";
import { defaultMessages } from "@/i18n";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";
import type { ResumeDetailResponse } from "@/types/api";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";
import { deferred } from "./helpers/pdf-browser-fixtures";
import { jsonResponse } from "./helpers/pdf-import-fixtures";

beforeEach(() => {
  clearApiCache();
  localStorage.clear();
  saveAuthSession("owner", "pdf-export-token", "2999-01-01T00:00:00Z");
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it.each([null, "generation", "download"] as const)(
  "saves then generates and downloads through the real authenticated PDF API (%s failure)",
  async (failure) => {
    const resume = createResumeDetailItem();
    const checkpoint: ResumeDetailResponse = {
      resume,
      savedAt: resume.updatedAt,
      versionId: "saved-version",
    };
    const saved = deferred<ResumeDetailResponse>();
    const generation = deferred<Response>();
    const download = deferred<Response>();
    const save = vi.fn(() => saved.promise);
    const requests: { path: string; init: RequestInit }[] = [];
    const artifact = {
      exportId: "export-a",
      fileName: "server filename.pdf",
      downloadUrl: "/api/exports/export-a/download",
      expiresAt: "2999-01-01T00:00:00Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
        const path = new URL(String(input), location.href).pathname;
        requests.push({ path, init });
        expect(new Headers(init.headers).get("Authorization")).toBe(
          "Bearer pdf-export-token",
        );
        if (path === "/api/exports/resume-pdf") return generation.promise;
        if (path === artifact.downloadUrl) return download.promise;
        throw new Error(`Unexpected PDF export request: ${path}`);
      }),
    );
    const createObjectURL = vi.fn<(blob: Blob) => string>(
      () => "blob:export-a",
    );
    const revokeObjectURL = vi.fn();
    vi.stubGlobal(
      "URL",
      class extends URL {
        static createObjectURL = createObjectURL;
        static revokeObjectURL = revokeObjectURL;
      },
    );
    const clicks: { href: string; download: string; connected: boolean }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push({
        href: this.href,
        download: this.download,
        connected: this.isConnected,
      });
    });
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const success = vi.spyOn(toast, "success").mockReturnValue("success-toast");
    const error = vi.spyOn(toast, "error").mockReturnValue("error-toast");
    const { result } = renderHook(() =>
      useResumeDetailExport({ messages: defaultMessages, save, templates: [] }),
    );
    let exporting!: Promise<void>;
    act(() => {
      exporting = result.current.exportPdf();
    });
    expect(result.current.isExporting).toBe(true);
    await act(() => vi.dynamicImportSettled());
    expect(requests).toEqual([]);
    await act(async () => {
      await result.current.exportPdf();
    });
    expect(save).toHaveBeenCalledTimes(1);
    await act(async () => saved.resolve(checkpoint));
    expect(requests).toHaveLength(1);
    expect(requests[0].path).toBe("/api/exports/resume-pdf");
    expect(requests[0].init.method).toBe("POST");
    expect(JSON.parse(String(requests[0].init.body))).toEqual({
      fileNameSeed: resume.title,
      resumeId: resume.id,
      savedAt: checkpoint.savedAt,
      versionId: checkpoint.versionId,
    });
    expect(success).not.toHaveBeenCalled();
    expect(clicks).toEqual([]);
    if (failure === "generation") {
      await act(async () => {
        generation.reject(new Error("Generation failed"));
        await exporting;
      });
      expect(requests).toHaveLength(1);
    } else {
      await act(async () => generation.resolve(jsonResponse(artifact)));
      expect(requests).toHaveLength(2);
      expect(requests[1].path).toBe(artifact.downloadUrl);
      expect(result.current.isExporting).toBe(true);
      expect(success).not.toHaveBeenCalled();
      expect(clicks).toEqual([]);
      await act(async () => {
        if (failure === "download")
          download.reject(new Error("Download failed"));
        else
          download.resolve(
            new Response("%PDF-test-artifact", {
              headers: { "Content-Type": "application/pdf" },
            }),
          );
        await exporting;
      });
    }
    expect(result.current.isExporting).toBe(false);
    expect(print).not.toHaveBeenCalled();
    expect(document.querySelector("iframe")).toBeNull();
    if (failure) {
      expect(error).toHaveBeenCalledTimes(1);
      expect(success).not.toHaveBeenCalled();
      expect(createObjectURL).not.toHaveBeenCalled();
      expect(clicks).toEqual([]);
    } else {
      expect(error).not.toHaveBeenCalled();
      expect(success).toHaveBeenCalledExactlyOnceWith(
        defaultMessages.exportSuccess,
        { closeButton: true },
      );
      expect(clicks).toEqual([
        { href: "blob:export-a", download: artifact.fileName, connected: true },
      ]);
      expect(createObjectURL).toHaveBeenCalledTimes(1);
      expect(await createObjectURL.mock.calls[0][0].text()).toBe(
        "%PDF-test-artifact",
      );
      expect(document.querySelector("a[download]")).toBeNull();
      await waitFor(() =>
        expect(revokeObjectURL).toHaveBeenCalledExactlyOnceWith(
          "blob:export-a",
        ),
      );
    }
  },
);

it("reports completed downloads in both locales", () => {
  expect(zh.exportSuccess).not.toMatch(/打开浏览器|打印|预览/);
  expect(en.exportSuccess).not.toMatch(/open(?:ing)? browser|print|preview/i);
});

it("reports a failed checkpoint once using the export fallback and never starts generation", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const failure = new Error("Internal checkpoint details");
  const error = vi.spyOn(toast, "error").mockReturnValue("checkpoint-error");
  const { result } = renderHook(() =>
    useResumeDetailExport({
      messages: defaultMessages,
      save: async () => {
        throw failure;
      },
      templates: [],
    }),
  );
  await act(async () => {
    await result.current.exportPdf();
  });
  expect(error).toHaveBeenCalledExactlyOnceWith(defaultMessages.exportFailed, {
    closeButton: true,
  });
  expect(fetch).not.toHaveBeenCalled();
  expect(result.current.isExporting).toBe(false);
});
