import assert from "node:assert/strict";
import { beforeEach, it, vi } from "vitest";
import {
  AGENT_MAX_WIDTH,
  AGENT_MIN_WIDTH,
  DEFAULT_AGENT_WIDTH,
  EDITOR_MAX_WIDTH,
  EDITOR_MIN_WIDTH,
  PREVIEW_MIN_WIDTH,
  getDefaultEditorWidth,
  readWorkspaceLayoutPreference,
  resolveWorkspaceWidths,
  writeWorkspaceLayoutPreference,
} from "@/components/workspace/resume-workspace-layout";

beforeEach(() => localStorage.clear());
it("keeps both resizable panes and preview within their constraints", () => {
  assert.equal(getDefaultEditorWidth(1000), EDITOR_MIN_WIDTH);
  assert.equal(getDefaultEditorWidth(1280), 377.6);
  assert.equal(getDefaultEditorWidth(2000), 432);
  assert.deepEqual(resolveWorkspaceWidths(1600, {}, true), {
    editorWidth: 432,
    agentWidth: DEFAULT_AGENT_WIDTH,
    editorMaxWidth: EDITOR_MAX_WIDTH,
    agentMaxWidth: AGENT_MAX_WIDTH,
  });

  const desired = { editorWidth: 560, agentWidth: 520, agentCollapsed: false };
  const constrained = resolveWorkspaceWidths(1280, desired, true);
  assert.deepEqual(constrained, {
    editorWidth: 560,
    agentWidth: 300,
    editorMaxWidth: 560,
    agentMaxWidth: 300,
  });
  assert.deepEqual(desired, {
    editorWidth: 560,
    agentWidth: 520,
    agentCollapsed: false,
  });
  assert.equal(resolveWorkspaceWidths(1600, desired, true).agentWidth, 520);
  assert.equal(resolveWorkspaceWidths(1280, desired, false).agentWidth, 520);

  for (const containerWidth of [0, 320, 960]) {
    for (const expanded of [false, true]) {
      const resolved = resolveWorkspaceWidths(
        containerWidth,
        desired,
        expanded,
      );
      assert(resolved.editorWidth >= EDITOR_MIN_WIDTH);
      assert(resolved.editorMaxWidth >= EDITOR_MIN_WIDTH);
      assert(resolved.agentWidth >= AGENT_MIN_WIDTH);
      assert(resolved.agentMaxWidth >= AGENT_MIN_WIDTH);
    }
  }

  for (const containerWidth of [1092, 1200, 1280, 1440, 1600, 2400]) {
    for (const editorWidth of [372, 432, 560]) {
      for (const agentWidth of [300, 360, 520]) {
        const resolved = resolveWorkspaceWidths(
          containerWidth,
          { editorWidth, agentWidth },
          true,
        );
        assert(resolved.editorWidth >= EDITOR_MIN_WIDTH);
        assert(resolved.agentWidth >= AGENT_MIN_WIDTH);
        assert(resolved.editorWidth <= resolved.editorMaxWidth);
        assert(resolved.agentWidth <= resolved.agentMaxWidth);
        assert(
          containerWidth - resolved.editorWidth - resolved.agentWidth >=
            PREVIEW_MIN_WIDTH,
        );
        assert(
          containerWidth - resolved.editorMaxWidth - resolved.agentWidth >=
            PREVIEW_MIN_WIDTH,
          "The editor drag limit must leave room for the current Agent width.",
        );
        assert(
          containerWidth - resolved.editorWidth - resolved.agentMaxWidth >=
            PREVIEW_MIN_WIDTH,
          "The Agent drag limit must leave room for the current editor width.",
        );
      }
    }
  }
});
it("validates, merges and preserves local layout preferences when space or storage is unavailable", () => {
  const storageKey = "reseno-workspace-layout-v1";
  assert.deepEqual(readWorkspaceLayoutPreference(), {});
  for (const raw of ["invalid-json", "null", "[]", "42"]) {
    localStorage.setItem(storageKey, raw);
    assert.deepEqual(readWorkspaceLayoutPreference(), {});
  }
  localStorage.setItem(
    storageKey,
    JSON.stringify({ editorWidth: 100, agentWidth: 900, agentCollapsed: true }),
  );
  assert.deepEqual(readWorkspaceLayoutPreference(), {
    editorWidth: EDITOR_MIN_WIDTH,
    agentWidth: AGENT_MAX_WIDTH,
    agentCollapsed: true,
  });
  localStorage.setItem(
    storageKey,
    JSON.stringify({ editorWidth: "500", agentWidth: null, agentCollapsed: 0 }),
  );
  assert.deepEqual(readWorkspaceLayoutPreference(), {});

  writeWorkspaceLayoutPreference({ editorWidth: 500, agentWidth: 380 });
  writeWorkspaceLayoutPreference({ agentCollapsed: false });
  writeWorkspaceLayoutPreference({ editorWidth: 540 });
  writeWorkspaceLayoutPreference({ agentWidth: Number.POSITIVE_INFINITY });
  assert.deepEqual(readWorkspaceLayoutPreference(), {
    editorWidth: 540,
    agentWidth: 380,
    agentCollapsed: false,
  });
  const savedPreference = localStorage.getItem(storageKey);
  resolveWorkspaceWidths(1280, readWorkspaceLayoutPreference(), true);
  assert.equal(localStorage.getItem(storageKey), savedPreference);

  vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new Error("Storage unavailable");
  });
  assert.deepEqual(readWorkspaceLayoutPreference(), {});
  assert.doesNotThrow(() =>
    writeWorkspaceLayoutPreference({ agentCollapsed: true }),
  );
});
