// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  deletePendingAgentAttachment,
  downloadAgentAttachment,
  uploadAgentAttachment,
} from "@/lib/agent-attachment-client";
import {
  loadAgentSession,
  loadAgentSessionRecovery,
  replaceAgentSession,
  stopAgentRun,
} from "@/lib/agent-session-run-client";
import { fetchApiResource, requestApi, uploadApi } from "@/lib/api-client";
import type { AgentSessionReplaceRequest } from "@/types/api";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  fetchApiResource: vi.fn(),
  requestApi: vi.fn(),
  uploadApi: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(requestApi).mockResolvedValue({});
  vi.mocked(uploadApi).mockResolvedValue({ id: "attachment-test" });
  vi.mocked(fetchApiResource).mockResolvedValue(new Response());
});

describe("Agent client protocol", () => {
  it.each([
    {
      name: "recovery",
      load: loadAgentSessionRecovery,
      route: "/api/agent/resumes/resume-run/recovery",
    },
    {
      name: "session",
      load: loadAgentSession,
      route: "/api/agent/resumes/resume-run/session",
    },
  ])(
    "loads uncached $name with the caller's abort signal",
    async ({ load, route }) => {
      const controller = new AbortController();
      await load("resume-run", { signal: controller.signal });
      expect(requestApi).toHaveBeenCalledExactlyOnceWith(route, {
        cacheTtlMs: 0,
        notifyOnError: undefined,
        signal: controller.signal,
      });
    },
  );
  it("stops the addressed run using DELETE", async () => {
    await stopAgentRun("run-stop");
    expect(requestApi).toHaveBeenCalledExactlyOnceWith(
      "/api/agent/runs/run-stop",
      { method: "DELETE" },
    );
  });
  it("passes the replacement payload unchanged with PUT", async () => {
    const replacement = {
      messages: [],
      revision: 7,
    } as unknown as AgentSessionReplaceRequest;
    await replaceAgentSession("resume-session", replacement);
    expect(requestApi).toHaveBeenCalledExactlyOnceWith(
      "/api/agent/resumes/resume-session/session",
      { method: "PUT", body: replacement },
    );
    expect(vi.mocked(requestApi).mock.calls[0][1]?.body).toBe(replacement);
  });
  it("uploads the same FormData with its owning resume, progress callback and signal", async () => {
    const controller = new AbortController();
    const body = new FormData();
    const onProgress = vi.fn();
    await uploadAgentAttachment(body, "resume-attachment", {
      onProgress,
      signal: controller.signal,
    });
    expect(uploadApi).toHaveBeenCalledExactlyOnceWith(
      "/api/agent/attachments",
      body,
      { onProgress, signal: controller.signal },
    );
    expect(vi.mocked(uploadApi).mock.calls[0][1]).toBe(body);
    expect(body.get("resumeId")).toBe("resume-attachment");
  });
  it("downloads an attachment without browser caching", async () => {
    await downloadAgentAttachment("resume-attachment", "attachment-download");
    expect(fetchApiResource).toHaveBeenCalledExactlyOnceWith(
      "/api/agent/resumes/resume-attachment/attachments/attachment-download",
      { cache: "no-store" },
    );
  });
  it.each([undefined, false])(
    "retains deletion notification semantics %s",
    async (notifyOnError) => {
      await deletePendingAgentAttachment(
        "resume-attachment",
        "attachment-delete",
        notifyOnError === undefined ? undefined : { notifyOnError },
      );
      expect(requestApi).toHaveBeenCalledExactlyOnceWith(
        "/api/agent/resumes/resume-attachment/attachments/attachment-delete",
        {
          method: "DELETE",
          ...(notifyOnError === undefined ? {} : { notifyOnError }),
        },
      );
      expect(vi.mocked(requestApi).mock.calls[0][1]?.notifyOnError).toBe(
        notifyOnError,
      );
    },
  );
});
