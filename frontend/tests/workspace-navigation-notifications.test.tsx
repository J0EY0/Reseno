import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Toaster, toast } from "sonner";

import {
  clearWorkspaceNavigationError,
  showWorkspaceNavigationError,
} from "@/components/workspace/workspace-navigation-notifications";

function frame() {
  act(() => vi.advanceTimersToNextFrame());
}

function publishError(message: string) {
  act(() => showWorkspaceNavigationError(message));
  act(() => vi.advanceTimersByTime(0));
}

function activeErrors() {
  return document.querySelectorAll(
    '[data-sonner-toast][data-type="error"]:not([data-removed="true"])',
  );
}

beforeEach(() => {
  vi.useFakeTimers({
    toFake: [
      "setTimeout",
      "clearTimeout",
      "requestAnimationFrame",
      "cancelAnimationFrame",
    ],
  });
  render(<Toaster />);
});

afterEach(() => {
  act(() => clearWorkspaceNavigationError());
  cleanup();
  toast.dismiss();
  vi.runOnlyPendingTimers();
  vi.clearAllTimers();
  vi.useRealTimers();
});

it("keeps the first navigation failure visible after clearing an empty notification", () => {
  act(() => clearWorkspaceNavigationError());
  frame();

  publishError("Could not open the resume.");
  expect(activeErrors()).toHaveLength(1);
  frame();

  expect(activeErrors()).toHaveLength(1);
  expect(screen.getByText("Could not open the resume.")).toBeTruthy();
});

it("keeps a retry failure when the previous notification finishes closing", () => {
  publishError("Could not open the resume.");
  frame();

  act(() => clearWorkspaceNavigationError());
  frame();
  publishError("The retry also failed.");
  frame();

  expect(activeErrors()).toHaveLength(1);
  expect(activeErrors()[0]?.textContent).toContain("The retry also failed.");

  act(() => vi.advanceTimersByTime(250));
  publishError("Could not open the template.");
  frame();

  expect(activeErrors()).toHaveLength(1);
  expect(activeErrors()[0]?.textContent).toContain(
    "Could not open the template.",
  );
});

it("updates one notification for failures within the same navigation attempt", () => {
  act(() => {
    showWorkspaceNavigationError("Could not open the resume.");
    showWorkspaceNavigationError("Could not open the template.");
  });
  act(() => vi.advanceTimersByTime(0));
  frame();

  expect(activeErrors()).toHaveLength(1);
  expect(screen.queryByText("Could not open the resume.")).toBeNull();
  expect(screen.getByText("Could not open the template.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Close toast" })).toBeTruthy();
});

it.each(["external dismiss", "close button", "expiration"] as const)(
  "keeps a new failure reported immediately after %s",
  (dismissal) => {
    publishError("Could not open the resume.");
    frame();

    if (dismissal === "external dismiss") {
      const previous = toast.getToasts()[0];
      expect(previous).toBeDefined();
      act(() => toast.dismiss(previous.id));
      frame();
    } else if (dismissal === "close button") {
      fireEvent.click(screen.getByRole("button", { name: "Close toast" }));
      expect(activeErrors()).toHaveLength(0);
    } else {
      act(() => vi.advanceTimersByTime(4000));
      expect(activeErrors()).toHaveLength(0);
    }

    publishError("Could not open the template.");
    frame();
    act(() => vi.advanceTimersByTime(250));

    expect(activeErrors()).toHaveLength(1);
    expect(activeErrors()[0]?.textContent).toContain(
      "Could not open the template.",
    );
  },
);
