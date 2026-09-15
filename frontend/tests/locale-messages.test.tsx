import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadMessages, type AppMessages, type Locale } from "@/i18n";
import en from "@/i18n/locales/en.json";
import zh from "@/i18n/locales/zh.json";
import { useLocaleMessages } from "@/i18n/use-locale-messages";

vi.mock("@/i18n", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/i18n")>()),
  loadMessages: vi.fn(),
}));
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
const error = new Error("Catalog unavailable");

beforeEach(() => {
  vi.mocked(loadMessages).mockReset();
  vi.mocked(loadMessages).mockImplementation(
    async (locale) => catalogs[locale],
  );
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});

function mount(initialLocale: Locale = "en", strict = false) {
  const snapshots: Array<ReturnType<typeof useLocaleMessages>> = [];
  const hook = renderHook(
    () => {
      const state = useLocaleMessages(initialLocale);
      snapshots.push(state);
      return state;
    },
    { reactStrictMode: strict },
  );
  return { ...hook, snapshots };
}
function expectReady(
  state: ReturnType<typeof useLocaleMessages>,
  locale: Locale,
  canPersistLocale = true,
) {
  expect(state).toMatchObject({
    locale,
    messages: catalogs[locale],
    isMessagesReady: true,
    canPersistLocale,
  });
}
function change(hook: ReturnType<typeof mount>, locale: Locale) {
  let pending!: Promise<boolean>;
  act(() => {
    pending = hook.result.current.changeLocale(locale);
  });
  return pending;
}

it("bootstraps English without loading a catalog", () => {
  const hook = mount();
  expectReady(hook.result.current, "en");
  expect(loadMessages).not.toHaveBeenCalled();
});

it.each([false, true])(
  "commits the initial catalog atomically with StrictMode=%s",
  async (strict) => {
    const gate = deferred();
    vi.mocked(loadMessages).mockReturnValue(gate.promise);
    const hook = mount("zh", strict);
    expect(hook.result.current).toMatchObject({
      locale: "zh",
      messages: en,
      isMessagesReady: false,
      canPersistLocale: false,
    });
    await act(async () => gate.resolve(zh));
    expectReady(hook.result.current, "zh");
    for (const state of hook.snapshots.filter((state) => state.isMessagesReady))
      expectReady(state, "zh");
  },
);

it.each(["resolve", "reject"] as const)(
  "ignores a late %s after the active locale is selected again",
  async (outcome) => {
    const gate = deferred();
    vi.mocked(loadMessages).mockReturnValue(gate.promise);
    const hook = mount();
    const pending = change(hook, "zh");
    await act(async () => {
      expect(await hook.result.current.changeLocale("en")).toBe(true);
    });
    await act(async () => {
      if (outcome === "resolve") gate.resolve(zh);
      else gate.reject(error);
      expect(await pending).toBe(false);
    });
    expectReady(hook.result.current, "en");
    expect(loadMessages).toHaveBeenCalledExactlyOnceWith("zh");
    expect(console.error).not.toHaveBeenCalled();
  },
);

it.each(["resolve", "reject"] as const)(
  "ignores an initial catalog's late %s after a newer choice succeeds",
  async (outcome) => {
    const old = deferred();
    vi.mocked(loadMessages).mockImplementation((locale) =>
      locale === "zh" ? old.promise : Promise.resolve(en),
    );
    const hook = mount("zh");
    await act(async () => {
      expect(await hook.result.current.changeLocale("en")).toBe(true);
    });
    await act(async () => {
      if (outcome === "resolve") old.resolve(zh);
      else old.reject(error);
    });
    expectReady(hook.result.current, "en");
    expect(console.error).not.toHaveBeenCalled();
  },
);

it.each(["en", "zh"] as const)(
  "requires an explicit %s choice before persisting after initial failure",
  async (choice) => {
    const gate = deferred();
    vi.mocked(loadMessages).mockReturnValueOnce(gate.promise);
    const hook = mount("zh");
    await act(async () => gate.reject(error));
    expectReady(hook.result.current, "en", false);
    expect(console.error).toHaveBeenCalledTimes(1);
    hook.rerender();
    expectReady(hook.result.current, "en", false);
    await act(async () => {
      expect(await hook.result.current.changeLocale(choice)).toBe(true);
    });
    expectReady(hook.result.current, choice);
    expect(loadMessages).toHaveBeenCalledTimes(choice === "en" ? 1 : 2);
  },
);

it("keeps the active snapshot during a failed switch and commits a retry atomically", async () => {
  const hook = mount();
  vi.mocked(loadMessages).mockRejectedValueOnce(error);
  await act(async () => {
    expect(await hook.result.current.changeLocale("zh")).toBe(false);
  });
  expectReady(hook.result.current, "en");
  const gate = deferred();
  vi.mocked(loadMessages).mockReturnValueOnce(gate.promise);
  const retry = change(hook, "zh");
  expectReady(hook.result.current, "en");
  await act(async () => {
    gate.resolve(zh);
    expect(await retry).toBe(true);
  });
  expectReady(hook.result.current, "zh");
  for (const state of hook.snapshots) expectReady(state, state.locale);
});

describe.each(["resolve", "reject"] as const)(
  "unmount before catalog %s",
  (outcome) => {
    it("invalidates the pending choice and performs no later render or error reporting", async () => {
      const gate = deferred();
      vi.mocked(loadMessages).mockReturnValue(gate.promise);
      const hook = mount();
      const pending = change(hook, "zh");
      hook.unmount();
      const renderCount = hook.snapshots.length;
      await act(async () => {
        if (outcome === "resolve") gate.resolve(zh);
        else gate.reject(error);
        expect(await pending).toBe(false);
      });
      expect(hook.snapshots).toHaveLength(renderCount);
      expect(console.error).not.toHaveBeenCalled();
    });
  },
);
