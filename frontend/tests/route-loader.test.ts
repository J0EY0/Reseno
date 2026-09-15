// @vitest-environment node
import { expect, it, vi } from "vitest";

import { createRouteLoader } from "@/lib/route-loader";

it("shares the same module promise between preload and rendering, including after completion", async () => {
  const module = Promise.withResolvers<{ Page: () => null }>();
  const load = vi.fn(() => module.promise);
  const loadPage = createRouteLoader(load, "Page");
  const preload = loadPage();
  expect(loadPage()).toBe(preload);
  expect(load).toHaveBeenCalledOnce();
  const Page = () => null;
  module.resolve({ Page });
  expect(await preload).toEqual({ default: Page });
  expect(loadPage()).toBe(preload);
  expect(load).toHaveBeenCalledOnce();
});
