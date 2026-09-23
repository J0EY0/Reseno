// @vitest-environment node
import { expect, it, vi } from "vitest";

import { requestApi } from "@/lib/api-client";
import { createResumeArtifact } from "@/lib/export-api";
import {
  createCustomTemplateFromBase,
  createTemplateLayout,
} from "@/lib/templates";
import { createTemplateApi, saveTemplateApi } from "@/lib/workspace-api";
import type { ResumeArtifactV1 } from "@/types/api";
import type { ResumeTemplateLayout } from "@/types/resume";

import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  requestApi: vi.fn(),
}));

it.each([
  ["minimal", "split", "list"],
  ["modern", "stacked", "inline"],
  ["compact", "compact", "columns"],
  ["classic", "split", "list"],
  ["executive", "compact", "list"],
  ["academic", "split", "list"],
] as const)(
  "%s preserves its default item layouts and inherits them for every module",
  (preset, timelineItemLayout, listItemLayout) => {
    expect(createTemplateLayout(preset)).toMatchObject({
      timelineItemLayout,
      listItemLayout,
      sectionItemLayouts: {},
    });
    expect(createTemplateLayout(preset).sectionItemLayouts).toEqual({});
  },
);

it.each(["split", "stacked", "compact", "inline"] as const)(
  "preserves %s globally and for every timeline module across normalization",
  (itemLayout) => {
    const overrides = {
      timelineItemLayout: itemLayout,
      sectionItemLayouts: {
        education: itemLayout,
        experience: itemLayout,
        project: itemLayout,
        publication: itemLayout,
        achievement: itemLayout,
      },
    };
    const layout = createTemplateLayout("modern", overrides);
    expect(layout).toMatchObject(overrides);
    expect(createTemplateLayout("modern", layout)).toEqual(layout);
  },
);

it("keeps sparse module overrides when the global layout changes", () => {
  const overrides = { education: "stacked", project: "inline" } as const;
  const layout = createTemplateLayout("minimal", {
    timelineItemLayout: "compact",
    sectionItemLayouts: overrides,
  });
  const changed = createTemplateLayout("minimal", {
    ...layout,
    timelineItemLayout: "inline",
  });
  expect(changed.timelineItemLayout).toBe("inline");
  expect(changed.sectionItemLayouts).toEqual(overrides);
});

it.each(["inherit", "list", "columns", "invalid", null, undefined, 42])(
  "drops invalid module layout %s without storing the global layout",
  (value) => {
    const layout = createTemplateLayout("minimal", {
      timelineItemLayout: "inline",
      sectionItemLayouts: {
        education: value,
        experience: "compact",
        simple_list: "inline",
        unknown: "split",
      } as ResumeTemplateLayout["sectionItemLayouts"],
    });
    expect(layout.sectionItemLayouts).toEqual({ experience: "compact" });
    expect(
      createTemplateLayout("minimal", {
        ...layout,
        timelineItemLayout: "stacked",
      }).sectionItemLayouts,
    ).toEqual({ experience: "compact" });
  },
);

it.each([null, undefined, "inline", 42, ["split"]])(
  "treats malformed module overrides %j as inherited layouts",
  (value) => {
    const layout = createTemplateLayout("minimal", {
      sectionItemLayouts: value as ResumeTemplateLayout["sectionItemLayouts"],
    });
    expect(layout.sectionItemLayouts).toEqual({});
  },
);

it("normalizes into independent module maps, including the default empty map", () => {
  const overrides = { education: "inline" } as const;
  const layout = createTemplateLayout("minimal", {
    sectionItemLayouts: overrides,
  });
  const normalized = createTemplateLayout("minimal", layout);
  normalized.sectionItemLayouts.education = "compact";
  expect(layout.sectionItemLayouts).toEqual({ education: "inline" });
  expect(overrides).toEqual({ education: "inline" });

  const firstDefault = createTemplateLayout("minimal");
  firstDefault.sectionItemLayouts.project = "inline";
  expect(createTemplateLayout("minimal").sectionItemLayouts).toEqual({});
});

it("copies a custom template without sharing its module overrides", () => {
  const base = createResumeDetailTemplate("custom-base", {
    layout: createTemplateLayout("minimal", {
      timelineItemLayout: "inline",
      sectionItemLayouts: { education: "stacked", project: "compact" },
    }),
  });
  const copy = createCustomTemplateFromBase(base);
  expect(copy.layout).toEqual(base.layout);
  copy.layout.sectionItemLayouts.education = "inline";
  delete copy.layout.sectionItemLayouts.project;
  expect(base.layout.sectionItemLayouts).toEqual({
    education: "stacked",
    project: "compact",
  });
});

it("preserves inline and sparse module layouts in create and checkpoint payloads", async () => {
  const template = createResumeDetailTemplate("custom-inline", {
    layout: createTemplateLayout("minimal", {
      timelineItemLayout: "inline",
      sectionItemLayouts: { education: "stacked", project: "inline" },
    }),
  });
  vi.mocked(requestApi).mockResolvedValue({ template });

  await createTemplateApi(template);
  await saveTemplateApi(template.id, template);

  expect(requestApi).toHaveBeenNthCalledWith(1, "/api/templates", {
    method: "POST",
    body: {
      template: expect.objectContaining({ layout: template.layout }),
    },
  });
  expect(requestApi).toHaveBeenNthCalledWith(
    2,
    "/api/templates/custom-inline",
    {
      method: "PUT",
      body: {
        saveMode: "checkpoint",
        template: expect.objectContaining({ layout: template.layout }),
      },
    },
  );
});

it("retains module layouts when an embedded custom template is serialized and normalized", () => {
  const template = createResumeDetailTemplate("custom-inline", {
    layout: createTemplateLayout("minimal", {
      timelineItemLayout: "inline",
      sectionItemLayouts: { publication: "compact", achievement: "inline" },
    }),
  });
  const resume = createResumeDetailItem({ template: template.id });
  const artifact = JSON.parse(
    JSON.stringify(createResumeArtifact(resume, template)),
  ) as ResumeArtifactV1;

  expect(artifact.resumes[0].template).toBe("custom:0");
  expect(artifact.templates).toHaveLength(1);
  expect(artifact.templates[0].ref).toBe("custom:0");
  const embedded = artifact.templates[0].definition;
  expect(embedded.layout).toEqual(template.layout);
  expect(createTemplateLayout(embedded.preset, embedded.layout)).toEqual(
    template.layout,
  );
});
