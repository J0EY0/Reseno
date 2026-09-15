import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { defaultMessages } from "@/i18n";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import { createEmptyResume } from "@/lib/resume";
import {
  createTemplateImageElement,
  getBuiltInTemplates,
} from "@/lib/templates";
import {
  createResumeDetailRouteHandoff,
  createTemplateDetailRouteHandoff,
  getResumeDetailRouteHandoff,
  getTemplateDetailRouteHandoff,
} from "@/lib/workspace-detail-route-handoff";
import {
  clearWorkspaceRouteHistoryState,
  deleteWorkspaceHandoffToken,
  releaseWorkspaceRouteHandoff,
} from "@/lib/workspace-route-handoff";
import {
  clearWorkspaceRouteMemory,
  createWorkspaceLateralRouteHandoff,
  getWorkspaceLateralRouteHandoff,
  rememberWorkspaceLateralRoute,
  resolveWorkspaceLateralRoute,
  type PreparedWorkspaceRoute,
} from "@/lib/workspace-route-memory";

const resume: PreparedWorkspaceRoute<"resume"> = {
  view: "resume",
  data: {
    customTemplates: [],
    defaultTemplateIds: { zh: "minimal", en: "classic" },
    resumes: [],
    theme: "light",
  },
};
const settings: PreparedWorkspaceRoute<"settings"> = {
  view: "settings",
  data: {
    agentSettings: normalizeAgentSettings({}),
    modelConfigs: [],
    theme: "dark",
  },
};

beforeEach(clearWorkspaceRouteMemory);
afterEach(() => {
  clearWorkspaceRouteMemory();
  window.history.replaceState(null, "", "/");
});

it("scrubs only the current entry without changing router metadata or URL", () => {
  const handoff = createWorkspaceLateralRouteHandoff(settings);
  const state = {
    idx: 3,
    key: "settings-current",
    masked: { pathname: "/workspace" },
    usr: handoff,
  };
  window.history.replaceState(state, "", "/settings?tab=models#active");
  const replace = vi.spyOn(window.history, "replaceState");
  clearWorkspaceRouteHistoryState("resume-stale");
  expect(window.history.state).toBe(state);
  expect(replace).not.toHaveBeenCalled();
  clearWorkspaceRouteHistoryState("settings-current");
  expect(window.history.state).toEqual({ ...state, usr: null });
  expect(
    window.location.pathname + window.location.search + window.location.hash,
  ).toBe("/settings?tab=models#active");
  expect(state.usr).toBe(handoff);
  clearWorkspaceRouteHistoryState("settings-current");
  expect(replace).toHaveBeenCalledTimes(1);
  window.history.replaceState(null, "");
  replace.mockClear();
  clearWorkspaceRouteHistoryState("settings-current");
  expect(replace).not.toHaveBeenCalled();
});

it("publishes a prepared snapshot before commit and keeps handoffs readable across initial renders", () => {
  const state = createWorkspaceLateralRouteHandoff(settings);
  expect(state).not.toHaveProperty("data");
  expect(getWorkspaceLateralRouteHandoff(state)).toBe(settings);
  expect(getWorkspaceLateralRouteHandoff(state)).toBe(settings);
  expect(
    getWorkspaceLateralRouteHandoff({ ...state, view: "resume" }),
  ).toBeNull();
  expect(getWorkspaceLateralRouteHandoff(null)).toBeNull();
  expect(resolveWorkspaceLateralRoute(null, "settings").data).toBe(
    settings.data,
  );
});

it("seeds POP from committed memory while consumed and cleared tokens cannot revive stale payloads", () => {
  rememberWorkspaceLateralRoute(resume);
  const state = createWorkspaceLateralRouteHandoff(settings);
  const arrival = resolveWorkspaceLateralRoute(state, "settings");
  expect(arrival).toEqual({
    data: settings.data,
    shouldScrubHistory: true,
    tokenToDelete: state.token,
  });
  expect(arrival.data).toBe(settings.data);
  deleteWorkspaceHandoffToken(arrival.tokenToDelete);
  expect(resolveWorkspaceLateralRoute(null, "resume").data).toBe(resume.data);
  expect(getWorkspaceLateralRouteHandoff(state)).toBeNull();
  const consumed = resolveWorkspaceLateralRoute(state, "settings");
  expect(consumed.data).toBe(settings.data);
  expect(consumed.shouldScrubHistory).toBe(true);
  clearWorkspaceRouteMemory();
  expect(resolveWorkspaceLateralRoute(null, "resume").data).toBeNull();
  expect(resolveWorkspaceLateralRoute(state, "settings")).toEqual({
    data: null,
    shouldScrubHistory: true,
    tokenToDelete: state.token,
  });
});

it("keeps large detail payloads out of history and releases each handoff independently", () => {
  const base = getBuiltInTemplates(defaultMessages)[0];
  const templateData = {
    customTemplates: [
      {
        ...base,
        id: "custom-a",
        layout: {
          ...base.layout,
          images: [
            {
              ...createTemplateImageElement(1, "Image"),
              src: "A".repeat(5 * 1024 * 1024),
            },
          ],
        },
      },
    ],
    defaultTemplateIds: { zh: "minimal", en: "minimal" },
    checkpoint: null,
  };
  const detailData = {
    detail: {
      resume: {
        id: "resume-a",
        title: "Resume",
        updatedAt: "now",
        documentLocale: "en" as const,
        resume: createEmptyResume(),
        jobBrief: "",
        template: "minimal",
        typography: base.typography,
        templateSettings: null,
      },
      savedAt: "now",
      versionId: "v1",
    },
    routeData: {
      ...templateData,
      modelConfigs: [],
      agentSettings: normalizeAgentSettings({}),
    },
    versions: [],
  };
  const detailState = createResumeDetailRouteHandoff(detailData, 1, 2);
  const templateState = createTemplateDetailRouteHandoff(
    "custom-a",
    templateData,
    "en",
  );
  for (const state of [detailState, templateState])
    expect(JSON.stringify(state).length).toBeLessThan(256);
  expect(
    getResumeDetailRouteHandoff(structuredClone(detailState), "resume-a")
      ?.payload,
  ).toBe(detailData);
  expect(
    getTemplateDetailRouteHandoff(structuredClone(templateState), "custom-a")
      ?.data,
  ).toBe(templateData);
  expect(getResumeDetailRouteHandoff(detailState, "another-resume")).toBeNull();
  expect(
    getResumeDetailRouteHandoff(
      { ...detailState, token: "missing" },
      "resume-a",
    ),
  ).toBeNull();
  expect(
    getTemplateDetailRouteHandoff(templateState, "another-template"),
  ).toBeNull();
  releaseWorkspaceRouteHandoff(detailState);
  expect(getResumeDetailRouteHandoff(detailState, "resume-a")).toBeNull();
  expect(
    getTemplateDetailRouteHandoff(templateState, "custom-a"),
  ).not.toBeNull();
  clearWorkspaceRouteMemory();
  expect(getResumeDetailRouteHandoff(detailState, "resume-a")).toBeNull();
  expect(getTemplateDetailRouteHandoff(templateState, "custom-a")).toBeNull();
});
