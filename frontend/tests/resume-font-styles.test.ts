// @vitest-environment node
import { expect, it, vi } from "vitest";
import { loadResumeFontStyles } from "@/components/preview/resume-font-loader";

const styles = vi.hoisted(() => ({ sans: vi.fn(), serif: vi.fn() }));
vi.mock("@/assets/fonts/resume-sans.css", () => {
  styles.sans();
  return {};
});
vi.mock("@/assets/fonts/resume-serif.css", () => {
  styles.serif();
  return {};
});

it("shares one optional font loading promise across each persisted font family", async () => {
  const sans = loadResumeFontStyles("inter");
  expect(loadResumeFontStyles("plex")).toBe(sans);
  expect(loadResumeFontStyles("noto_sans_sc")).toBe(sans);
  const serif = loadResumeFontStyles("serif");
  expect(loadResumeFontStyles("times")).toBe(serif);
  expect(serif).not.toBe(sans);
  await Promise.all([sans, serif]);
  expect(styles.sans).toHaveBeenCalledOnce();
  expect(styles.serif).toHaveBeenCalledOnce();
  expect(loadResumeFontStyles("inter")).toBe(sans);
});
