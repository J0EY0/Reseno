import { act, fireEvent, render, screen } from "@testing-library/react";
import { ErrorBoundary } from "react-error-boundary";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ResourceRecoveryContext } from "@/components/resource-recovery-context";
import { ResumeWorkspaceColumns } from "@/components/workspace/resume-workspace-columns";
import { TemplateWorkspaceColumns } from "@/components/workspace/template-workspace-columns";
import en from "@/i18n/locales/en.json";

const resource = vi.hoisted(() => ({ failed: false }));
vi.mock("@/components/workspace/workspace-panel-resizer", () => ({
  default: () => {
    if (resource.failed) {
      throw new TypeError(
        "Failed to fetch dynamically imported module: /resizer.js",
      );
    }
    return <span>Resize available</span>;
  },
}));

beforeEach(() => {
  resource.failed = false;
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("matchMedia", () => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
});
afterEach(() => vi.unstubAllGlobals());

it.each(["template", "resume"] as const)(
  "keeps %s edits and preview mounted when the resizer resource fails",
  async (kind) => {
    const saveAndReload = vi.fn(async () => {});
    function View() {
      const editor = <input aria-label="Name" defaultValue="Original" />;
      const preview = <div role="img" aria-label="Preview" />;
      return (
        <ErrorBoundary fallback={<span>Page unavailable</span>}>
          <ResourceRecoveryContext value={{ messages: en, saveAndReload }}>
            {kind === "template" ? (
              <TemplateWorkspaceColumns locale="en" editor={editor}>
                {preview}
              </TemplateWorkspaceColumns>
            ) : (
              <ResumeWorkspaceColumns
                locale="en"
                editor={editor}
                preview={preview}
                agent={null}
                agentExpanded={false}
              />
            )}
          </ResourceRecoveryContext>
        </ErrorBoundary>
      );
    }
    const { rerender } = render(<View />);
    await screen.findByText("Resize available");
    const name = screen.getByRole<HTMLInputElement>("textbox", {
      name: "Name",
    });
    const preview = screen.getByRole("img", { name: "Preview" });
    fireEvent.change(name, { target: { value: "Unsaved" } });
    resource.failed = true;
    rerender(<View />);
    expect(screen.queryByText("Page unavailable")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Name" })).toBe(name);
    expect(name.value).toBe("Unsaved");
    expect(screen.getByRole("img", { name: "Preview" })).toBe(preview);
    expect(screen.getByRole("alert").textContent).toContain(
      en.resourceLoadError,
    );
    fireEvent.click(screen.getByRole("button", { name: en.saveAndReload }));
    await act(async () => {});
    expect(saveAndReload).toHaveBeenCalledOnce();
  },
);
