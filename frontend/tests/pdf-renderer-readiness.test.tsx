import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PdfExportRenderer } from "@/components/pdf-export-renderer";
import { clearApiCache } from "@/lib/api-client";
import { saveAuthSession } from "@/lib/auth-session";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";
import {
  deferred,
  installFonts,
  installFrames,
  installPreviewGeometry,
} from "./helpers/pdf-browser-fixtures";
import { jsonResponse } from "./helpers/pdf-import-fixtures";

let restoreFonts: () => void;
beforeEach(() => {
  clearApiCache();
  localStorage.clear();
  saveAuthSession("owner", "pdf-export-token", "2999-01-01T00:00:00Z");
  vi.stubGlobal("ResizeObserver", undefined);
});
afterEach(() => {
  cleanup();
  restoreFonts?.();
  document
    .querySelectorAll("[data-test-render-asset]")
    .forEach((node) => node.remove());
  vi.unstubAllGlobals();
  localStorage.clear();
  delete window.__RESENO_PDF_READY__;
  delete window.__RESENO_PDF_ERROR__;
});

it.each(["assets-last", "pagination-last"])(
  "publishes readiness only after real preview pagination and assets settle (%s)",
  async (order) => {
    const fonts = deferred<void>();
    restoreFonts = installFonts(fonts.promise);
    const frames = installFrames();
    const geometry = installPreviewGeometry();
    const image = document.createElement("img");
    image.dataset.testRenderAsset = "true";
    image.src = "/fixture.png";
    const decoded = deferred<void>();
    Object.defineProperty(image, "complete", { value: false });
    Object.defineProperty(image, "decode", { value: () => decoded.promise });
    document.body.append(image);
    const resume = createResumeDetailItem();
    const requests: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
        const path = new URL(String(input), location.href).pathname;
        requests.push(path);
        expect(new Headers(init.headers).get("Authorization")).toBe(
          "Bearer pdf-export-token",
        );
        if (path === "/api/workspace/pages/templates")
          return jsonResponse({
            customTemplates: [],
            defaultTemplateIds: { en: "minimal", zh: "minimal" },
          });
        if (path === "/api/resumes/resume-a/versions/version-a")
          return jsonResponse({
            resume,
            savedAt: resume.updatedAt,
            versionId: "version-a",
          });
        throw new Error(`Unexpected PDF renderer request: ${path}`);
      }),
    );
    const print = vi.spyOn(window, "print").mockImplementation(() => undefined);
    const { container } = render(
      <MemoryRouter
        initialEntries={[
          "/pdf-export?documentLocale=en&resumeId=resume-a&versionId=version-a&print=1",
        ]}
      >
        <PdfExportRenderer />
      </MemoryRouter>,
    );
    const ready = () =>
      container.querySelector("main")?.getAttribute("data-pdf-ready");
    expect(ready()).toBe("false");
    await waitFor(() =>
      expect(container.querySelector(".resume-page-stack")).not.toBeNull(),
    );
    expect(requests.sort()).toEqual([
      "/api/resumes/resume-a/versions/version-a",
      "/api/workspace/pages/templates",
    ]);
    await act(() => vi.dynamicImportSettled());
    await frames.frame();
    expect(ready()).toBe("false");
    expect(window.__RESENO_PDF_READY__).toBe(false);
    await act(async () => fonts.resolve());
    if (order === "assets-last") {
      await frames.frame();
      await frames.frame();
      expect(
        container
          .querySelector(".resume-page-stack")
          ?.getAttribute("data-resume-pagination-ready"),
      ).toBe("true");
      expect(ready()).toBe("false");
      await act(async () => decoded.resolve());
    } else {
      await act(async () => decoded.resolve());
      for (const height of [800, 500, 800, 500]) {
        geometry.contentHeight = height;
        await frames.frame();
      }
      expect(ready()).toBe("false");
    }
    await frames.frame();
    if (order === "assets-last") {
      expect(ready()).toBe("false");
      await frames.frame();
    }
    expect(ready()).toBe("true");
    expect(window.__RESENO_PDF_READY__).toBe(true);
    expect(window.__RESENO_PDF_ERROR__).toBeUndefined();
    expect(print).not.toHaveBeenCalled();
    expect(container.querySelector("iframe")).toBeNull();
  },
);

it("rejects invalid document locale before fetching or advertising export readiness", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(
    <MemoryRouter initialEntries={["/pdf-export?resumeId=resume-a"]}>
      <PdfExportRenderer />
    </MemoryRouter>,
  );
  expect(screen.getByText("Invalid document locale.")).toBeTruthy();
  expect(window.__RESENO_PDF_READY__).toBe(false);
  expect(window.__RESENO_PDF_ERROR__).toBe("Invalid document locale.");
  expect(fetch).not.toHaveBeenCalled();
});

it("publishes an export load error without leaving a ready document", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("PDF data unavailable");
    }),
  );
  const { container } = render(
    <MemoryRouter
      initialEntries={["/pdf-export?documentLocale=en&resumeId=missing"]}
    >
      <PdfExportRenderer />
    </MemoryRouter>,
  );
  await waitFor(() => expect(window.__RESENO_PDF_ERROR__).toBeTruthy());
  expect(container.querySelector("main")?.getAttribute("data-pdf-ready")).toBe(
    "false",
  );
  expect(window.__RESENO_PDF_READY__).toBe(false);
  expect(container.querySelector(".resume-page-stack")).toBeNull();
});
