import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  readWorkspaceLayoutPreference,
  writeWorkspaceLayoutPreference,
} from "@/components/workspace/resume-workspace-layout";
import { useResumeDetailAgentLayout } from "@/components/workspace/use-resume-detail-agent-layout";

vi.mock("@/components/workspace/resume-workspace-layout", () => ({
  readWorkspaceLayoutPreference: vi.fn(),
  writeWorkspaceLayoutPreference: vi.fn(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe.each([false, true])("Agent layout with wide viewport %s", (wide) => {
  it.each([undefined, false, true])(
    "preserves the user's choice with saved collapsed preference %s",
    (savedCollapsed) => {
      let matches = wide;
      const media = new EventTarget();
      const matchMedia = vi.fn(() => ({
        get matches() {
          return matches;
        },
        media: "(min-width: 1536px)",
        addEventListener: media.addEventListener.bind(media),
        removeEventListener: media.removeEventListener.bind(media),
      }));
      vi.stubGlobal("matchMedia", matchMedia);
      vi.mocked(readWorkspaceLayoutPreference).mockReturnValue({
        agentCollapsed: savedCollapsed,
        editorWidth: 432,
        agentWidth: 360,
      });

      const hook = renderHook(() => useResumeDetailAgentLayout("resume-1"));
      const initiallyCollapsed = savedCollapsed ?? !wide;
      expect(hook.result.current.isPanelCollapsed).toBe(initiallyCollapsed);
      expect(writeWorkspaceLayoutPreference).not.toHaveBeenCalled();

      act(() => {
        hook.result.current.setIsPanelCollapsed(!initiallyCollapsed);
      });
      expect(hook.result.current.isPanelCollapsed).toBe(!initiallyCollapsed);
      expect(writeWorkspaceLayoutPreference).toHaveBeenCalledExactlyOnceWith({
        agentCollapsed: !initiallyCollapsed,
      });

      act(() => {
        matches = !wide;
        media.dispatchEvent(
          Object.assign(new Event("change"), {
            matches,
            media: "(min-width: 1536px)",
          }),
        );
        window.dispatchEvent(new Event("resize"));
      });
      hook.rerender();
      expect(hook.result.current.isPanelCollapsed).toBe(!initiallyCollapsed);
      expect(writeWorkspaceLayoutPreference).toHaveBeenCalledTimes(1);
      expect(readWorkspaceLayoutPreference).toHaveBeenCalledTimes(1);
    },
  );
});
