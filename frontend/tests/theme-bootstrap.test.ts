import html from "../index.html?raw";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.className = "";
  document.documentElement.style.colorScheme = "";
});

it.each([
  ["dark", false, false, "dark"],
  ["light", true, false, "light"],
  ["system", true, false, "dark"],
  ["system", false, false, "light"],
  ["invalid", false, false, "light"],
  ["dark", false, true, "light"],
] as const)(
  "bootstraps saved %s with system dark %s and blocked storage %s",
  (saved, systemDark, blocked, expected) => {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    const page = frame.contentWindow!;
    page.localStorage.setItem("reseno-theme", saved);
    Object.defineProperty(page, "matchMedia", {
      value: vi.fn(() => ({ matches: systemDark })),
    });
    if (blocked)
      Object.defineProperty(page, "localStorage", {
        get: () => {
          throw new Error("Storage unavailable");
        },
      });
    const pageDocument = page.document;
    pageDocument.open();
    pageDocument.write(html);
    pageDocument.close();
    expect(pageDocument.documentElement.classList.contains("dark")).toBe(
      expected === "dark",
    );
    expect(pageDocument.documentElement.style.colorScheme).toBe(expected);
    const scripts = [...pageDocument.querySelectorAll("script")];
    expect(
      scripts.findIndex((script) =>
        script.hasAttribute("data-reseno-theme-bootstrap"),
      ),
    ).toBeLessThan(scripts.findIndex((script) => script.type === "module"));
    frame.remove();
  },
);
