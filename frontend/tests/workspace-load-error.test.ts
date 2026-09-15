import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { loadMessages } from "@/i18n";
import { notifyApiError } from "@/lib/api-error-notifier";
import { ApiError } from "@/lib/api-errors";
import {
  dismissWorkspaceLoadError,
  showWorkspaceLoadError,
} from "@/lib/workspace-load-error";
import { saveLocalePreference } from "@/lib/workspace-storage";

vi.mock("sonner", () => ({ toast: { error: vi.fn(), dismiss: vi.fn() } }));
vi.mock("@/lib/auth-session", () => ({ getAccessToken: () => "active-token" }));
const visible = new Map<string | number, unknown>();
const events: string[] = [];

beforeEach(() => {
  saveLocalePreference("en");
  visible.clear();
  visible.set("unrelated", "Saved successfully");
  events.length = 0;
  let nextId = 0;
  vi.mocked(toast.error).mockImplementation((message, options) => {
    expect(options).toEqual({ closeButton: true });
    const id = nextId++;
    visible.set(id, message);
    events.push(`show:${id}`);
    return id;
  });
  vi.mocked(toast.dismiss).mockImplementation((id) => {
    expect(id).toBeDefined();
    visible.delete(id!);
    events.push(`dismiss:${id}`);
    return id!;
  });
});
afterEach(dismissWorkspaceLoadError);

it("gives repeated failures fresh IDs, replaces only the prior error, and dismisses each once", () => {
  dismissWorkspaceLoadError();
  dismissWorkspaceLoadError();
  expect(events).toEqual([]);
  for (let attempt = 0; attempt < 3; attempt++) {
    showWorkspaceLoadError(new Error("Network unavailable"), "Request failed");
    expect(visible.get(attempt)).toBe("Request failed");
    dismissWorkspaceLoadError();
    dismissWorkspaceLoadError();
  }
  expect(events).toEqual([
    "show:0",
    "dismiss:0",
    "show:1",
    "dismiss:1",
    "show:2",
    "dismiss:2",
  ]);
  showWorkspaceLoadError(new Error("First"), "First route failed");
  showWorkspaceLoadError(new Error("Second"), "Second route failed");
  expect(events.slice(-3)).toEqual(["show:3", "dismiss:3", "show:4"]);
  expect([...visible]).toEqual([
    ["unrelated", "Saved successfully"],
    [4, "Second route failed"],
  ]);
  dismissWorkspaceLoadError();
  dismissWorkspaceLoadError();
  expect([...visible]).toEqual([["unrelated", "Saved successfully"]]);
});

it.each(["already notified", "aborted"])(
  "keeps existing toasts unchanged for an %s error",
  (kind) => {
    showWorkspaceLoadError(new Error("Existing"), "Existing route failed");
    const error =
      kind === "aborted"
        ? new DOMException("Cancelled", "AbortError")
        : new ApiError("UNAUTHORIZED_REQUEST");
    if (kind === "already notified") expect(notifyApiError(error)).toBe(true);
    const previousEvents = [...events];
    const previousToasts = [...visible];
    showWorkspaceLoadError(error, "Route failed");
    expect(events).toEqual(previousEvents);
    expect([...visible]).toEqual(previousToasts);
  },
);

it.each(["en", "zh"] as const)(
  "preserves structured API messages in %s",
  async (locale) => {
    const messages = await loadMessages(locale);
    expect(messages.loadError).toBe(messages.apiMessages.REQUEST_FAILED);
    expect(messages.retry).toBe(locale === "zh" ? "重试" : "Retry");
    expect(messages.contentNotLoaded).toBe(
      locale === "zh" ? "当前内容未加载" : "Content isn't loaded",
    );
    expect(messages.loadError).not.toMatch(
      /回退|空白简历|fall(?:ing)? back|empty resume|remote data/i,
    );
    saveLocalePreference(locale);
    for (const [key, expected] of [
      ["NOT_FOUND", messages.apiMessages.NOT_FOUND],
      ["RESOURCE_NOT_FOUND", messages.apiMessages.REQUEST_FAILED],
    ]) {
      showWorkspaceLoadError(new ApiError(key), "Route failed");
      expect(toast.error).toHaveBeenLastCalledWith(expected, {
        closeButton: true,
      });
      expect([...visible.values()]).toEqual(["Saved successfully", expected]);
    }
  },
);
