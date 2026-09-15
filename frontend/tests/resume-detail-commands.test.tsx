import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DocumentCanvasHandle } from "@/components/preview/document-canvas";
import type { useResumeDetailCommands } from "@/components/workspace/use-resume-detail-commands";
import { defaultMessages } from "@/i18n";
import type {
  fitResumeToOnePage,
  SmartOnePageStyleSnapshot,
} from "@/lib/smart-one-page";

import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

type CommandsOptions = Parameters<typeof useResumeDetailCommands>[0];

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() },
}));

beforeEach(() => vi.resetModules());
afterEach(() => vi.doUnmock("@/lib/smart-one-page"));

async function renderCommands() {
  const document = createResumeDetailItem();
  const template = createResumeDetailTemplate("minimal");
  const style: SmartOnePageStyleSnapshot = {
    typography: { ...document.typography, fontSize: 14 },
    templateSettings: { pagePaddingX: 18 },
  };
  const ready = Promise.withResolvers<void>();
  const started = Promise.withResolvers<void>();
  const fit = vi.fn<typeof fitResumeToOnePage>(
    async (previous, _settings, adapter) => {
      adapter.applyStyle(style);
      await adapter.measurePageCount();
      return { status: "applied", previous, style };
    },
  );
  const load = vi.fn(async () => {
    started.resolve();
    await ready.promise;
    return { fitResumeToOnePage: fit };
  });
  vi.doMock("@/lib/smart-one-page", load);
  const { useResumeDetailCommands } =
    await import("@/components/workspace/use-resume-detail-commands");
  const options: CommandsOptions = {
    activeTemplate: template,
    isLoading: false,
    messages: defaultMessages,
    navigateToResume: vi.fn(),
    previewResume: document.resume,
    resumeOrdinal: 1,
    save: {
      hasUnsavedChanges: vi.fn(() => false),
      save: vi.fn<CommandsOptions["save"]["save"]>(),
      saveState: "saved",
    },
    session: {
      document,
      fingerprint: "original",
      resume: document.resume,
      template: document.template,
      templateSettings: document.templateSettings,
      typography: document.typography,
      applyTemplate: vi.fn(),
      rename: vi.fn(),
      updateStyle: vi.fn(),
    },
    templateCatalog: [template],
  };
  const hook = renderHook(useResumeDetailCommands, { initialProps: options });
  const measure = vi
    .fn<DocumentCanvasHandle["measurePageCount"]>()
    .mockResolvedValue(1);
  hook.result.current.documentPreviewRef.current = {
    measurePageCount: measure,
  };
  act(() => hook.result.current.setPreviewReady(true));
  function start() {
    let running!: Promise<void>;
    act(() => {
      running = hook.result.current.fitOnePage();
    });
    return running;
  }
  return { ...hook, options, style, ready, started, fit, load, measure, start };
}

describe("smart one-page command", () => {
  it("loads on click, prevents duplicate work and applies one measured result", async () => {
    const f = await renderCommands();
    expect(f.load).not.toHaveBeenCalled();
    expect(f.result.current.isSmartFitting).toBe(false);
    const running = f.start();
    await f.started.promise;
    expect(f.result.current.isSmartFitting).toBe(true);
    await act(async () => {
      await f.result.current.fitOnePage();
    });
    expect(f.load).toHaveBeenCalledTimes(1);
    expect(f.fit).not.toHaveBeenCalled();
    expect(f.measure).not.toHaveBeenCalled();
    expect(f.options.session.updateStyle).not.toHaveBeenCalled();

    await act(async () => {
      f.ready.resolve();
      await running;
    });
    expect(f.fit).toHaveBeenCalledTimes(1);
    expect(f.fit.mock.calls[0][0]).toEqual({
      typography: f.options.session.typography,
      templateSettings: f.options.session.templateSettings,
    });
    expect(f.measure).toHaveBeenCalledExactlyOnceWith(
      expect.any(AbortSignal),
      f.style,
    );
    expect(f.measure.mock.calls[0][0].aborted).toBe(false);
    expect(f.options.session.updateStyle).toHaveBeenCalledExactlyOnceWith(
      f.style,
    );
    expect(f.result.current.previewStyle).toBeNull();
    expect(f.result.current.isSmartFitting).toBe(false);
    expect(toast.success).toHaveBeenCalledOnce();
  });

  it.each(["document change", "preview change", "unmount"] as const)(
    "cancels during module loading after %s before fitting or measuring",
    async (change) => {
      const f = await renderCommands();
      const running = f.start();
      await f.started.promise;
      if (change === "unmount") f.unmount();
      else
        f.rerender({
          ...f.options,
          ...(change === "document change"
            ? { session: { ...f.options.session, fingerprint: "changed" } }
            : { previewResume: structuredClone(f.options.previewResume) }),
        });
      await act(async () => {
        f.ready.resolve();
        await running;
      });
      expect(f.load).toHaveBeenCalledOnce();
      expect(f.fit).not.toHaveBeenCalled();
      expect(f.measure).not.toHaveBeenCalled();
      expect(f.options.session.updateStyle).not.toHaveBeenCalled();
      expect(toast.success).not.toHaveBeenCalled();
      expect(toast.info).not.toHaveBeenCalled();
      expect(toast.error).not.toHaveBeenCalled();
      if (change !== "unmount") {
        expect(f.result.current.previewStyle).toBeNull();
        expect(f.result.current.isSmartFitting).toBe(false);
      }
    },
  );

  it.each(["unchanged", "typography", "templateSettings"] as const)(
    "only undoes the still-current fitted style after %s",
    async (change) => {
      const f = await renderCommands();
      f.ready.resolve();
      await act(async () => {
        await f.result.current.fitOnePage();
      });
      const action = vi.mocked(toast.success).mock.calls[0]?.[1]?.action;
      if (!action || typeof action !== "object" || !("onClick" in action)) {
        throw new Error("The fitted result must provide an undo action.");
      }
      f.rerender({
        ...f.options,
        session: {
          ...f.options.session,
          ...f.style,
          ...(change === "unchanged"
            ? {}
            : { [change]: { ...f.style[change] } }),
        },
      });
      render(<button onClick={action.onClick}>Undo</button>);
      fireEvent.click(screen.getByRole("button", { name: "Undo" }));
      expect(f.options.session.updateStyle).toHaveBeenCalledTimes(
        change === "unchanged" ? 2 : 1,
      );
      if (change === "unchanged") {
        expect(f.options.session.updateStyle).toHaveBeenLastCalledWith({
          typography: f.options.session.typography,
          templateSettings: f.options.session.templateSettings,
        });
      }
    },
  );
});
