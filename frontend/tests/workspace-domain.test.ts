// @vitest-environment node
import { expect, it, vi } from "vitest";

import { normalizeResumeTitle, truncateResumeTitle } from "@/lib/resume-title";
import {
  fitResumeToOnePage,
  type SmartOnePageStyleSnapshot,
} from "@/lib/smart-one-page";
import {
  getBuiltInTemplates,
  resumeFontSizeOptions,
  createCustomTemplateFromBase,
  createTemplateLayout,
  createTemplateSettings,
} from "@/lib/templates";
import {
  countResumeChanges,
  createResumeFingerprint,
} from "@/lib/workspace-change-tracking";
import { getWorkspaceRoute } from "@/lib/workspace-route";
import { getMessagesSync } from "@/i18n";
import { getBuiltinTemplatePreset } from "@/lib/template-presets";
import backendPresets from "../../backend/app/services/template_presets.json";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";

it("ignores server metadata and preferences while counting edited document leaves", () => {
  const original = {
    ...createResumeDetailItem(),
    savedAt: "before",
    theme: "light",
    agentSettings: { defaultModelConfigId: "a" },
  };
  const metadata = {
    ...original,
    updatedAt: "later",
    savedAt: "later",
    theme: "dark",
    agentSettings: { defaultModelConfigId: "b" },
  };
  expect(createResumeFingerprint(metadata)).toBe(
    createResumeFingerprint(original),
  );
  expect(countResumeChanges(original, metadata)).toBe(0);
  const edited = {
    ...metadata,
    resume: {
      ...metadata.resume,
      basic: { ...metadata.resume.basic, name: "Grace" },
    },
  };
  expect(countResumeChanges(original, edited)).toBe(1);
});

it.each([
  ["already-one-page", false],
  ["applied", false],
  ["no-fit", false],
  ["applied", true],
] as const)(
  "smart fit returns %s only after measuring the document (compact=%s)",
  async (status, compact) => {
    const current: SmartOnePageStyleSnapshot = {
      typography: { fontFamily: "inter", fontSize: 16 },
      templateSettings: null,
    };
    const settings = {
      ...createTemplateSettings("minimal"),
      pagePaddingTop: 16,
      pagePaddingX: 16,
      pagePaddingBottom: 16,
      sectionGap: compact ? 0.6 : 1.4,
      itemGap: 1,
      bodyLineHeight: compact ? 1.15 : 1.7,
      nameScale: 2,
      sectionTitleScale: 1.2,
      itemTitleScale: 1,
      metaScale: 0.9,
      bodyScale: 1,
    };
    const applyStyle = vi.fn();
    const measurePageCount = vi.fn(async () => (status === "no-fit" ? 2 : 1));
    if (status === "applied") measurePageCount.mockResolvedValueOnce(2);
    const result = await fitResumeToOnePage(current, settings, {
      applyStyle,
      measurePageCount,
    });
    if (result.status === "applied") {
      expect(result).toEqual({
        status,
        previous: current,
        style: applyStyle.mock.calls[0][0],
      });
      expect(applyStyle).toHaveBeenCalledOnce();
      if (compact)
        expect(result.style.templateSettings).toMatchObject({
          sectionGap: 0.6,
          bodyLineHeight: 1.15,
        });
    } else {
      expect(result).toEqual({ status });
      if (status === "no-fit")
        expect(applyStyle.mock.calls.length).toBeGreaterThan(1);
      else expect(applyStyle).not.toHaveBeenCalled();
    }
  },
);

it("keeps a readable font when tighter spacing fits before the next smaller size", async () => {
  const current: SmartOnePageStyleSnapshot = {
    typography: { fontFamily: "inter", fontSize: 16 },
    templateSettings: null,
  };
  let rendered = current;
  const applyStyle = vi.fn((style: SmartOnePageStyleSnapshot) => {
    rendered = style;
  });
  const result = await fitResumeToOnePage(
    current,
    createTemplateSettings("minimal"),
    {
      applyStyle,
      measurePageCount: async () =>
        rendered.typography.fontSize <= 14 &&
        (rendered.templateSettings?.itemGap ?? Infinity) <= 0.5 &&
        (rendered.templateSettings?.bodyLineHeight ?? Infinity) <= 1.42
          ? 1
          : 2,
    },
  );
  expect(result.status).toBe("applied");
  expect(rendered.typography.fontSize).toBe(14);
  expect(
    applyStyle.mock.calls.every(([style]) => style.typography.fontSize >= 14),
  ).toBe(true);
});

it.each([
  ["/resume", { kind: "resume-gallery" }],
  ["/resume/abc", { kind: "resume-detail", id: "abc" }],
  ["/templates", { kind: "template-gallery" }],
  ["/template/minimal", { kind: "template-detail", id: "minimal" }],
  ["/trash", { kind: "trash" }],
  ["/models", { kind: "models" }],
  ["/settings", { kind: "settings" }],
  ["/unknown", { kind: "unknown" }],
])("parses %s into its canonical route", (path, route) =>
  expect(getWorkspaceRoute(path as string)).toEqual(route),
);

it("bounds Unicode titles by characters and supplies a blank title default", () => {
  expect(Array.from(truncateResumeTitle("😀".repeat(60)))).toHaveLength(50);
  expect(normalizeResumeTitle("   ", "Fallback")).toBe("Fallback");
});

it("preserves built-in spacing and duplicated custom typography and layout", () => {
  const defaults = {
    minimal: 0.7,
    modern: 0.6,
    compact: 0.7,
    classic: 0.8,
    executive: 0.7,
    academic: 1.2,
  } as const;
  for (const id of Object.keys(defaults) as (keyof typeof defaults)[])
    expect(createTemplateSettings(id).sectionGap).toBe(defaults[id]);
  expect(
    createTemplateSettings("minimal", { sectionGap: 0.6 }).sectionGap,
  ).toBe(0.6);
  const template = createCustomTemplateFromBase({
    id: "compact-serif",
    preset: "minimal",
    name: "Compact serif",
    description: "",
    layout: { ...createTemplateLayout("minimal"), section: "underlined" },
    typography: { fontFamily: "times", fontSize: 14 },
    settings: createTemplateSettings("minimal", { bodyLineHeight: 1.15 }),
    updatedAt: "",
    isBuiltIn: false,
  });
  expect(template).toMatchObject({
    layout: { section: "underlined" },
    typography: { fontFamily: "times", fontSize: 14 },
    settings: { bodyLineHeight: 1.15 },
  });
});

it("keeps every built-in preset typography valid and independent of edited catalog entries", () => {
  const messages = getMessagesSync("en");
  const catalog = getBuiltInTemplates(messages);
  expect(catalog.map(({ id }) => id).sort()).toEqual(
    Object.keys(backendPresets).sort(),
  );
  for (const template of catalog) {
    const expected =
      backendPresets[template.id as keyof typeof backendPresets].typography;
    expect(["inter", "noto_sans_sc", "plex", "serif", "times"]).toContain(
      template.typography.fontFamily,
    );
    expect(resumeFontSizeOptions).toContain(template.typography.fontSize);
    expect(template.typography).toEqual(expected);
    template.typography.fontFamily = "noto_sans_sc";
    template.typography.fontSize = 20;
    expect(getBuiltinTemplatePreset(template.preset).typography).toEqual(
      expected,
    );
    expect(
      getBuiltInTemplates(messages).find(({ id }) => id === template.id)
        ?.typography,
    ).toEqual(expected);
  }
});
