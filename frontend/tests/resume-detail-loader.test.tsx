import { act, fireEvent, render, renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useResumeDetailLoader } from "@/components/workspace/use-resume-detail-loader";
import { loadResumeDetailRouteData } from "@/components/workspace/workspace-route-preparation";
import { WorkspaceRouteError } from "@/components/workspace/workspace-route-error";
import { getMessagesSync } from "@/i18n";
import { normalizeAgentSettings } from "@/lib/agent-settings";
import {
  dismissWorkspaceLoadError,
  showWorkspaceLoadError,
} from "@/lib/workspace-load-error";
import type { WorkspacePreferencesPersistence } from "@/lib/workspace-preferences-persistence";
import type { PreparedResumeDetailRouteData } from "@/lib/workspace-route-data";
import { createResumeDetailItem } from "./helpers/resume-detail-fixtures";

vi.mock("@/components/workspace/workspace-route-preparation", () => ({
  loadResumeDetailRouteData: vi.fn(),
}));
vi.mock("@/components/preview/document-canvas-loader", () => ({
  loadDocumentCanvas: vi.fn(),
}));
vi.mock("@/lib/workspace-load-error", () => ({
  dismissWorkspaceLoadError: vi.fn(),
  showWorkspaceLoadError: vi.fn(),
}));

const prepared: PreparedResumeDetailRouteData = {
  detail: { resume: createResumeDetailItem(), savedAt: "now", versionId: "v1" },
  routeData: {
    theme: "light",
    modelConfigs: [],
    agentSettings: normalizeAgentSettings(null),
    defaultTemplateIds: { en: "minimal", zh: "minimal" },
    customTemplates: [],
  },
  versions: [],
};
const persistence = {} as WorkspacePreferencesPersistence;
beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => vi.useRealTimers());

function mount(
  initialPreparedData: PreparedResumeDetailRouteData | null = null,
) {
  const onLoad = vi.fn();
  return {
    onLoad,
    ...renderHook(
      ({ resumeId, loaded = onLoad }) =>
        useResumeDetailLoader({
          initialPreparedData,
          locale: "en",
          onLoad: loaded,
          persistence,
          resumeId,
        }),
      {
        initialProps: { resumeId: "resume-a", loaded: onLoad },
        wrapper: StrictMode,
      },
    ),
  };
}
const start = () => act(() => vi.advanceTimersByTimeAsync(0));

it("consumes a prepared detail exactly once in StrictMode without fetching", () => {
  const view = mount(prepared);
  expect(view.onLoad).toHaveBeenCalledExactlyOnceWith(prepared);
  expect(loadResumeDetailRouteData).not.toHaveBeenCalled();
  expect(view.result.current).toMatchObject({
    hasLoaded: true,
    isLoading: false,
    hasLoadError: false,
  });
});

it("does not start the deferred request after immediate unmount", async () => {
  mount().unmount();
  await start();
  expect(loadResumeDetailRouteData).not.toHaveBeenCalled();
});

it("starts one request in StrictMode and commits through the latest onLoad callback", async () => {
  const response = Promise.withResolvers<PreparedResumeDetailRouteData>();
  vi.mocked(loadResumeDetailRouteData).mockReturnValue(response.promise);
  const view = mount();
  await start();
  expect(loadResumeDetailRouteData).toHaveBeenCalledOnce();
  const loaded = vi.fn();
  view.rerender({ resumeId: "resume-a", loaded });
  await act(async () => response.resolve(prepared));
  expect(view.onLoad).not.toHaveBeenCalled();
  expect(loaded).toHaveBeenCalledExactlyOnceWith(prepared);
  expect(view.result.current).toMatchObject({
    hasLoaded: true,
    isLoading: false,
    hasLoadError: false,
  });
});

it("exposes a failed load, retries once and clears the error only when the retry completes", async () => {
  const error = new Error("Load failed");
  const retry = Promise.withResolvers<PreparedResumeDetailRouteData>();
  vi.mocked(loadResumeDetailRouteData)
    .mockRejectedValueOnce(error)
    .mockReturnValueOnce(retry.promise);
  const view = mount();
  await start();
  expect(view.result.current).toMatchObject({
    hasLoaded: false,
    isLoading: false,
    hasLoadError: true,
  });
  expect(view.onLoad).not.toHaveBeenCalled();
  expect(showWorkspaceLoadError).toHaveBeenCalledExactlyOnceWith(
    error,
    getMessagesSync("en").apiMessages.REQUEST_FAILED,
  );
  act(view.result.current.retryLoad);
  await start();
  expect(view.result.current).toMatchObject({
    hasLoaded: false,
    isLoading: true,
    hasLoadError: false,
  });
  expect(dismissWorkspaceLoadError).toHaveBeenCalledTimes(2);
  await act(async () => retry.resolve(prepared));
  expect(view.onLoad).toHaveBeenCalledExactlyOnceWith(prepared);
  expect(view.result.current).toMatchObject({
    hasLoaded: true,
    isLoading: false,
    hasLoadError: false,
  });
});

it.each(["success", "failure", "abort"])(
  "ignores a superseded request's late %s",
  async (outcome) => {
    const old = Promise.withResolvers<PreparedResumeDetailRouteData>();
    const current = Promise.withResolvers<PreparedResumeDetailRouteData>();
    vi.mocked(loadResumeDetailRouteData)
      .mockReturnValueOnce(old.promise)
      .mockReturnValueOnce(current.promise);
    const view = mount();
    await start();
    const signal = vi.mocked(loadResumeDetailRouteData).mock.calls[0][2].signal;
    view.rerender({ resumeId: "resume-b", loaded: view.onLoad });
    expect(signal.aborted).toBe(true);
    await start();
    await act(async () =>
      outcome === "success"
        ? old.resolve(prepared)
        : old.reject(
            outcome === "abort"
              ? new DOMException("Cancelled", "AbortError")
              : new Error("Old failure"),
          ),
    );
    expect(view.onLoad).not.toHaveBeenCalled();
    expect(showWorkspaceLoadError).not.toHaveBeenCalled();
    expect(view.result.current.isLoading).toBe(true);
    await act(async () => current.resolve(prepared));
    expect(view.onLoad).toHaveBeenCalledOnce();
  },
);

it("keeps the unloaded surface neutral and lets the user retry", () => {
  const onRetry = vi.fn();
  const messages = getMessagesSync("en");
  const view = render(
    <WorkspaceRouteError messages={messages} onRetry={onRetry} />,
  );
  expect(view.getByText(messages.contentNotLoaded)).toBeTruthy();
  expect(view.queryByRole("alert")).toBeNull();
  fireEvent.click(view.getByRole("button", { name: messages.retry }));
  expect(onRetry).toHaveBeenCalledOnce();
});
