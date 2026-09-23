import { beforeEach, expect, it, vi } from "vitest";

import {
  readTemplateEditorWidth,
  resolveTemplateWorkspaceWidth,
  writeTemplateEditorWidth,
} from "@/components/workspace/template-workspace-layout";

beforeEach(() => localStorage.clear());

it("keeps the preview visible while preserving the chosen width across languages and smaller containers", () => {
  expect(resolveTemplateWorkspaceWidth(1440, undefined, "zh")).toEqual({
    minimum: 340,
    maximum: 560,
    width: 340,
  });
  expect(resolveTemplateWorkspaceWidth(1440, undefined, "en")).toEqual({
    minimum: 400,
    maximum: 560,
    width: 400,
  });
  writeTemplateEditorWidth(480);
  expect(
    resolveTemplateWorkspaceWidth(860, readTemplateEditorWidth(), "zh").width,
  ).toBe(440);
  expect(readTemplateEditorWidth()).toBe(480);
  expect(
    resolveTemplateWorkspaceWidth(1440, readTemplateEditorWidth(), "en").width,
  ).toBe(480);
  expect(resolveTemplateWorkspaceWidth(1440, 340, "en").width).toBe(400);
});

it("validates persisted widths without changing resume layout preferences", () => {
  localStorage.setItem(
    "reseno-workspace-layout-v1",
    '{"editorWidth":500,"agentWidth":380}',
  );
  for (const raw of ["invalid", "null", "[]", '"500"']) {
    localStorage.setItem("reseno-template-editor-width-v1", raw);
    expect(readTemplateEditorWidth()).toBeUndefined();
  }
  writeTemplateEditorWidth(900);
  expect(readTemplateEditorWidth()).toBe(560);
  writeTemplateEditorWidth(Number.NaN);
  expect(readTemplateEditorWidth()).toBe(560);
  writeTemplateEditorWidth(100);
  expect(readTemplateEditorWidth()).toBe(340);
  expect(localStorage.getItem("reseno-workspace-layout-v1")).toBe(
    '{"editorWidth":500,"agentWidth":380}',
  );
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new Error("Storage unavailable");
  });
  expect(readTemplateEditorWidth()).toBeUndefined();
  expect(() => writeTemplateEditorWidth(480)).not.toThrow();
});
