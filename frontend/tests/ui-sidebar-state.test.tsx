import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getInitialSidebarOpen } from "@/components/ui/sidebar-state";
import {
  SidebarProvider,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";

beforeEach(() => {
  document.cookie = "sidebar_state=; max-age=0; path=/";
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});
afterEach(() => {
  document.cookie = "sidebar_state=; max-age=0; path=/";
  vi.unstubAllGlobals();
});
it.each([
  [undefined, true, true],
  [undefined, false, false],
  ["", true, true],
  ["sidebar_state=invalid", false, false],
  ["other=value; sidebar_state=true", false, true],
  ["sidebar_state=false; other=value", true, false],
] as const)(
  "reads saved sidebar cookie %s with default %s",
  (cookie, fallback, expected) => {
    if (cookie === undefined) vi.stubGlobal("document", undefined);
    else vi.spyOn(document, "cookie", "get").mockReturnValue(cookie);
    try {
      expect(getInitialSidebarOpen(fallback)).toBe(expected);
    } finally {
      vi.unstubAllGlobals();
    }
  },
);
it.each([true, false])(
  "uses the saved %s state on its first render and persists button/keyboard toggles",
  (saved) => {
    document.cookie = `sidebar_state=${saved}; path=/`;
    const states: boolean[] = [];
    function State() {
      const sidebar = useSidebar();
      states.push(sidebar.open);
      return <output>{sidebar.state}</output>;
    }
    render(
      <SidebarProvider defaultOpen={!saved}>
        <SidebarTrigger />
        <State />
      </SidebarProvider>,
    );
    expect(states[0]).toBe(saved);
    expect(screen.getByRole("status").textContent).toBe(
      saved ? "expanded" : "collapsed",
    );
    fireEvent.click(screen.getByRole("button", { name: "Toggle Sidebar" }));
    expect(document.cookie).toContain(`sidebar_state=${!saved}`);
    fireEvent.keyDown(window, { key: "b", ctrlKey: true });
    expect(document.cookie).toContain(`sidebar_state=${saved}`);
    fireEvent.keyDown(window, { key: "b", metaKey: true });
    expect(document.cookie).toContain(`sidebar_state=${!saved}`);
  },
);
