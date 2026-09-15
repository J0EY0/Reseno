// @vitest-environment node
import { beforeEach, expect, it, vi } from "vitest";

import { importResumesIntoWorkspace } from "@/components/workspace/resume-gallery-import";
import { defaultMessages } from "@/i18n";
import { importResumePayload } from "@/lib/import-api";
import { createEmptyResume } from "@/lib/resume";
import { getBuiltInTemplates } from "@/lib/templates";
import { createResumeApi, createTemplateApi } from "@/lib/workspace-api";
import type { ImportResumeResponse, ResumeArtifactItem } from "@/types/api";

vi.mock("@/lib/import-api", () => ({ importResumePayload: vi.fn() }));
vi.mock("@/lib/workspace-api", () => ({
  createResumeApi: vi.fn(),
  createTemplateApi: vi.fn(),
}));
const file = new File(["{}"], "backup.json", { type: "application/json" });
const baseTemplate = getBuiltInTemplates(defaultMessages)[0];
const item = (
  title: string,
  template: ResumeArtifactItem["template"] = "minimal",
): ResumeArtifactItem => ({
  title,
  template,
  documentLocale: "en",
  resume: createEmptyResume(),
  jobBrief: "",
  typography: baseTemplate.typography,
  templateSettings: null,
});
const templates: ImportResumeResponse["templates"] = [
  { ref: "custom:0", definition: { ...baseTemplate, name: "A" } },
  { ref: "custom:1", definition: { ...baseTemplate, name: "B" } },
];

beforeEach(() =>
  vi.spyOn(console, "error").mockImplementation(() => undefined),
);

function prepare(
  bundle: ImportResumeResponse,
  failResume?: string,
  failTemplate?: string,
) {
  vi.mocked(importResumePayload).mockResolvedValue(bundle);
  vi.mocked(createTemplateApi).mockImplementation(async (definition) => {
    if (failTemplate !== undefined && definition.name === failTemplate) {
      failTemplate = undefined;
      throw new Error("Template rejected");
    }
    return {
      template: {
        ...baseTemplate,
        ...definition,
        id: `template-${definition.name}`,
      },
    };
  });
  vi.mocked(createResumeApi).mockImplementation(async (request) => {
    if (failResume !== undefined && request.title === failResume) {
      failResume = undefined;
      throw new Error("Resume rejected");
    }
    return {
      resume: {
        ...item(request.title!),
        ...request,
        id: `resume-${request.title}`,
        updatedAt: "now",
      },
      savedAt: "now",
      versionId: "1",
    };
  });
}

it("publishes partial successes and retries only unfinished resumes", async () => {
  prepare(
    {
      templates,
      resumes: [
        item("1", "custom:0"),
        item("2", "custom:1"),
        item("3"),
        item("4"),
        item("5"),
      ],
    },
    "4",
  );
  const published: string[] = [];
  const options = {
    onResumeSaved: (saved: Awaited<ReturnType<typeof createResumeApi>>) =>
      published.push(saved.resume.title),
  };
  const first = await importResumesIntoWorkspace(file, options);
  expect(published).toEqual(["1", "2", "3", "5"]);
  expect(first).toMatchObject({ importedCount: 4, remainingCount: 1 });
  const second = await first.retry!(options);
  expect(second).toMatchObject({
    importedCount: 5,
    remainingCount: 0,
    retry: null,
  });
  expect(
    vi
      .mocked(createTemplateApi)
      .mock.calls.map(([definition]) => definition.name),
  ).toEqual(["A", "B"]);
  expect(
    vi.mocked(createResumeApi).mock.calls.map(([request]) => request.title),
  ).toEqual(["1", "2", "3", "4", "5", "4"]);
});

it("delays only dependents of a failed embedded template and reuses successful templates", async () => {
  prepare(
    {
      templates,
      resumes: [item("A", "custom:0"), item("B", "custom:1"), item("plain")],
    },
    undefined,
    "A",
  );
  const first = await importResumesIntoWorkspace(file);
  expect(first.remainingCount).toBe(1);
  expect(
    vi.mocked(createResumeApi).mock.calls.map(([request]) => request.title),
  ).toEqual(["B", "plain"]);
  const second = await first.retry!({});
  expect(second.remainingCount).toBe(0);
  expect(
    vi
      .mocked(createTemplateApi)
      .mock.calls.map(([definition]) => definition.name),
  ).toEqual(["A", "B", "A"]);
  expect(
    vi.mocked(createResumeApi).mock.calls.map(([request]) => request.template),
  ).toEqual(["template-B", "minimal", "template-A"]);
});

it("keeps committed imports on cancellation and resumes the remaining batch", async () => {
  prepare({ templates: [], resumes: [item("1"), item("2"), item("3")] });
  const controller = new AbortController();
  const first = await importResumesIntoWorkspace(file, {
    signal: controller.signal,
    onResumeSaved: () => controller.abort(),
  });
  expect(first).toMatchObject({ importedCount: 1, remainingCount: 2 });
  expect(createResumeApi).toHaveBeenCalledOnce();
  const second = await first.retry!({});
  expect(second).toMatchObject({ importedCount: 3, remainingCount: 0 });
  expect(
    vi.mocked(createResumeApi).mock.calls.map(([request]) => request.title),
  ).toEqual(["1", "2", "3"]);
});
