// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AppMessages, Locale } from "@/i18n";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";
import type { AgentSessionResponse } from "@/types/api";

const catalogs = { en, zh };
function deferred<T = AppMessages>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

beforeEach(() => vi.resetModules());
afterEach(() => {
  vi.doUnmock("@/i18n");
  vi.doUnmock("@/i18n/locales/zh.json");
});

describe("locale catalog loading", () => {
  it("keeps English synchronous, shares pending Chinese loads, and caches success", async () => {
    const gate = deferred<{ default: AppMessages }>();
    const loadCatalog = vi.fn(() => gate.promise);
    vi.doMock("@/i18n/locales/zh.json", loadCatalog);
    const i18n = await import("@/i18n");
    expect(i18n.getMessagesSync("en")).toEqual(en);
    expect(i18n.getLoadedMessages("en")).toBe(i18n.defaultMessages);
    expect(await i18n.loadMessages("en")).toBe(i18n.defaultMessages);
    expect(i18n.getLoadedMessages("zh")).toBeNull();
    expect(i18n.getMessagesSync("zh")).toBe(i18n.defaultMessages);
    expect(loadCatalog).not.toHaveBeenCalled();
    const first = i18n.loadMessages("zh");
    expect(i18n.loadMessages("zh")).toBe(first);
    await vi.waitFor(() => expect(loadCatalog).toHaveBeenCalledTimes(1));
    gate.resolve({ default: zh });
    expect(await first).toBe(zh);
    expect(i18n.getLoadedMessages("zh")).toBe(zh);
    expect(i18n.getMessagesSync("zh")).toBe(zh);
    expect(await i18n.loadMessages("zh")).toBe(zh);
    expect(loadCatalog).toHaveBeenCalledTimes(1);
  });

  it("clears a failed import so the same locale module can retry", async () => {
    const loadCatalog = vi.fn(() => {
      throw new Error("Catalog unavailable");
    });
    vi.doMock("@/i18n/locales/zh.json", loadCatalog);
    const i18n = await import("@/i18n");
    const failed = i18n.loadMessages("zh");
    expect(i18n.loadMessages("zh")).toBe(failed);
    await expect(failed).rejects.toThrow();
    expect(i18n.getLoadedMessages("zh")).toBeNull();
    vi.doMock("@/i18n/locales/zh.json", () => ({ default: zh }));
    const retry = i18n.loadMessages("zh");
    expect(retry).not.toBe(failed);
    expect(await retry).toBe(zh);
    expect(i18n.getLoadedMessages("zh")).toBe(zh);
    expect(loadCatalog).toHaveBeenCalledTimes(1);
  });
});

it.each(["session", "en", "zh"] as const)(
  "hydrates multilingual Agent history only after %s settles last",
  async (last) => {
    const pending = {
      session: deferred<AgentSessionResponse>(),
      en: deferred<AppMessages>(),
      zh: deferred<AppMessages>(),
    };
    const loadMessages = vi.fn((locale: Locale) => pending[locale].promise);
    vi.doMock("@/i18n", () => ({ locales: ["zh", "en"], loadMessages }));
    const { hydrateAgentSession, toPanelMessages } =
      await import("@/components/copilot/copilot-message-model");
    const transient = Object.values(catalogs).flatMap(
      (t) => t.agentTransientModelStatusTexts,
    );
    const session: AgentSessionResponse = {
      resumeId: "resume-1",
      revision: "revision-1",
      executions: [],
      messages: [
        ...transient.map((text, index) => ({
          id: `status-${index}`,
          createdAt: "2026-09-01T00:00:00Z",
          role: "assistant" as const,
          text,
        })),
        {
          id: "content",
          createdAt: "2026-09-01T00:00:00Z",
          role: "assistant",
          text: "Keep the actual answer",
        },
      ],
    };
    const expected = [...transient.map(() => ""), "Keep the actual answer"];
    expect(
      toPanelMessages(session, transient).map((message) => message.text),
    ).toEqual(expected);
    const settled = vi.fn();
    const hydration = hydrateAgentSession(pending.session.promise).then(
      (value) => {
        settled();
        return value;
      },
    );
    expect(loadMessages.mock.calls.map(([locale]) => locale).sort()).toEqual([
      "en",
      "zh",
    ]);
    const finish = {
      session: () => pending.session.resolve(session),
      en: () => pending.en.resolve(en),
      zh: () => pending.zh.resolve(zh),
    };
    for (const key of ["session", "en", "zh"] as const)
      if (key !== last) finish[key]();
    await new Promise<void>((resolve) => setImmediate(resolve));
    expect(settled).not.toHaveBeenCalled();
    finish[last]();
    const result = await hydration;
    expect(result.session).toBe(session);
    expect(result.panelMessages.map((message) => message.text)).toEqual(
      expected,
    );
    expect(result.draftSnapshot).toBeNull();
  },
);
