import { act } from "@testing-library/react";
import { useEffect, type ComponentProps } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ResumePreview } from "@/components/preview/resume-preview";
import { fitImportedResumeToOnePage } from "@/components/workspace/pdf-import-layout";
import { getLoadedMessages, loadMessages } from "@/i18n";
import { createTemplateSettings, getBuiltInTemplates } from "@/lib/templates";
import { fetchWorkspaceRouteData } from "@/lib/workspace-api";
import type { DocumentLocale } from "@/types/resume";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

type PreviewProps = ComponentProps<typeof ResumePreview>;
const preview = {
  renders: [] as PreviewProps[],
  unmounts: 0,
  automaticPageCount: null as number | null,
};
vi.mock("@/components/preview/resume-preview", () => ({
  ResumePreview: function Preview(props: PreviewProps) {
    useEffect(() => {
      preview.renders.push(props);
      if (preview.automaticPageCount !== null) {
        props.onPaginationReadyChange?.(true, preview.automaticPageCount);
      }
      return () => {
        preview.unmounts += 1;
      };
    }, [props]);
    return <div data-testid="pdf-import-preview" />;
  },
}));
vi.mock("@/lib/workspace-api", () => ({
  fetchWorkspaceRouteData: vi.fn(),
}));

const controllers: AbortController[] = [];
const resume = createResumeDetailItem().resume;
const customTemplate = createResumeDetailTemplate("custom-zh", {
  typography: { fontFamily: "serif", fontSize: 20 },
  settings: createTemplateSettings("minimal", {
    pagePaddingTop: 22,
    bodyColor: "#123456",
  }),
});

beforeEach(async () => {
  preview.renders = [];
  preview.unmounts = 0;
  preview.automaticPageCount = null;
  await loadMessages("zh");
  vi.mocked(fetchWorkspaceRouteData).mockResolvedValue({
    kind: "template-gallery",
    data: {
      customTemplates: [customTemplate],
      defaultTemplateIds: { en: "classic", zh: customTemplate.id },
    },
  });
});
afterEach(async () => {
  await act(async () => {
    controllers.splice(0).forEach((controller) => controller.abort());
  });
});

async function startFit(locale: DocumentLocale = "zh") {
  const controller = new AbortController();
  controllers.push(controller);
  const resolved = vi.fn();
  const rejected = vi.fn();
  let request!: ReturnType<typeof fitImportedResumeToOnePage>;
  await act(async () => {
    request = fitImportedResumeToOnePage(resume, locale, controller.signal);
    void request.then(resolved, rejected);
  });
  return { request, controller, resolved, rejected };
}

async function reportPagination(ready: boolean, count: number) {
  await act(async () => {
    preview.renders.at(-1)!.onPaginationReadyChange?.(ready, count);
  });
}

it.each(["en", "zh"] as const)(
  "measures with the %s document's saved default template and messages",
  async (locale) => {
    preview.automaticPageCount = 1;
    const messages = getLoadedMessages(locale)!;
    const expected =
      locale === "zh"
        ? customTemplate
        : getBuiltInTemplates(messages).find(({ id }) => id === "classic")!;
    const fit = await startFit(locale);

    expect(fetchWorkspaceRouteData).toHaveBeenCalledWith("template-gallery", {
      signal: fit.controller.signal,
      notifyOnError: false,
    });
    expect(preview.renders).toHaveLength(1);
    const rendered = preview.renders[0];
    expect(rendered.resume).toBe(resume);
    expect(rendered.t).toBe(messages);
    expect(rendered.template).toEqual(expected);
    expect(rendered.fontFamily).toBe(expected.typography.fontFamily);
    expect(rendered.fontSize).toBe(expected.typography.fontSize);
    await expect(fit.request).resolves.toEqual({
      template: expected.id,
      typography: expected.typography,
      templateSettings: null,
    });
    expect(preview.unmounts).toBe(1);
    expect(
      document.querySelector('[data-testid="pdf-import-preview"]'),
    ).toBeNull();
  },
);

it("returns a fitting candidate only after that candidate's pagination is ready", async () => {
  const fit = await startFit();
  await reportPagination(false, 1);
  expect(fit.resolved).not.toHaveBeenCalled();
  expect(preview.renders).toHaveLength(1);

  await reportPagination(true, 2);
  expect(preview.renders).toHaveLength(2);
  const candidate = preview.renders.at(-1)!;
  expect(candidate.template.settings.pagePaddingTop).toBeLessThan(
    customTemplate.settings.pagePaddingTop,
  );
  await reportPagination(false, 1);
  expect(fit.resolved).not.toHaveBeenCalled();

  await reportPagination(true, 1);
  await expect(fit.request).resolves.toEqual({
    template: customTemplate.id,
    typography: {
      fontFamily: candidate.fontFamily,
      fontSize: candidate.fontSize,
    },
    templateSettings: candidate.template.settings,
  });
  expect(preview.unmounts).toBe(preview.renders.length);
  expect(
    document.querySelector('[data-testid="pdf-import-preview"]'),
  ).toBeNull();
});

it("cancels a pending candidate, removes its hidden host and produces no saveable style", async () => {
  const fit = await startFit();
  await reportPagination(true, 2);
  const pendingCandidate = preview.renders.at(-1)!;
  const host = document.querySelector(
    '[data-testid="pdf-import-preview"]',
  )!.parentElement!;
  expect(host.getAttribute("aria-hidden")).toBe("true");
  expect(host.style.visibility).toBe("hidden");
  expect(host.inert).toBe(true);

  await act(async () => fit.controller.abort());
  await expect(fit.request).rejects.toMatchObject({ name: "AbortError" });
  expect(host.isConnected).toBe(false);
  expect(preview.unmounts).toBe(preview.renders.length);
  expect(fit.resolved).not.toHaveBeenCalled();

  await act(async () => {
    pendingCandidate.onPaginationReadyChange?.(true, 1);
  });
  expect(fit.resolved).not.toHaveBeenCalled();
  expect(preview.renders).toHaveLength(2);
});

it("returns the original template style when every measured candidate still exceeds one page", async () => {
  preview.automaticPageCount = 2;
  const fit = await startFit();

  expect(preview.renders.length).toBeGreaterThan(2);
  const lastCandidate = preview.renders.at(-1)!;
  expect(lastCandidate.fontSize).toBeLessThan(
    customTemplate.typography.fontSize,
  );
  expect(lastCandidate.template.settings).not.toEqual(customTemplate.settings);
  await expect(fit.request).resolves.toEqual({
    template: customTemplate.id,
    typography: customTemplate.typography,
    templateSettings: null,
  });
  expect(preview.unmounts).toBe(preview.renders.length);
  expect(
    document.querySelector('[data-testid="pdf-import-preview"]'),
  ).toBeNull();
});
