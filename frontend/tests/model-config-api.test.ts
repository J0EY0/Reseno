// @vitest-environment node
import { expect, it, vi } from "vitest";
import { requestApi } from "@/lib/api-client";
import { getModelProviders } from "@/lib/model-config-api";
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  requestApi: vi.fn(),
}));
it("shares provider reads, keeps failures local and permits retry after a rejected request", async () => {
  const pending = Promise.withResolvers<{ providers: [] }>();
  vi.mocked(requestApi).mockReturnValue(pending.promise);
  const first = getModelProviders();
  expect(getModelProviders()).toBe(first);
  expect(requestApi).toHaveBeenCalledExactlyOnceWith("/api/model-providers", {
    notifyOnError: false,
  });
  const error = new Error("Metadata unavailable");
  const failed = expect(first).rejects.toBe(error);
  pending.reject(error);
  await failed;
  const payload = { providers: [] };
  vi.mocked(requestApi).mockResolvedValue(payload);
  const retry = getModelProviders();
  expect(retry).not.toBe(first);
  expect(await retry).toBe(payload);
  expect(getModelProviders()).toBe(retry);
  expect(requestApi).toHaveBeenCalledTimes(2);
});
