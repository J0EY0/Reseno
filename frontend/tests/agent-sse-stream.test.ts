// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  connectAgentRun,
  sendAgentChatMessage,
} from "@/lib/agent-stream-client";
import { clearApiCache, fetchApiResource } from "@/lib/api-client";
import type { AgentChatRequest, AgentRunResponse } from "@/types/api";

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  clearApiCache: vi.fn(),
  fetchApiResource: vi.fn(),
}));
vi.mock("@/lib/auth-session", () => ({
  getAccessToken: () => "agent-test-token",
}));

function activeRun(): AgentRunResponse {
  return {
    baseResume: null,
    errorCode: null,
    executionState: "running",
    id: "run-reconnect-test",
    lastEventId: 0,
    resumeId: null,
    status: "active",
  } as unknown as AgentRunResponse;
}
function eventStream(body = "", headers = {}) {
  return new Response(body, {
    headers: { "Content-Type": "text/event-stream", ...headers },
    status: 200,
  });
}
const transport = vi.mocked(fetchApiResource);

beforeEach(() => {
  transport.mockReset();
  vi.useFakeTimers();
  vi.stubGlobal("window", { setTimeout, clearTimeout });
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Agent SSE reconnects", () => {
  it.each([false, true])(
    "resets the retry budget after progress across nine streams (abrupt=%s)",
    async (abrupt) => {
      const cursors: number[] = [];
      transport.mockImplementation(async (route) => {
        cursors.push(
          Number(new URL(route, "http://agent.test").searchParams.get("after")),
        );
        const id = cursors.length;
        const event =
          id === 9
            ? `id: ${id}\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}\n\n`
            : `id: ${id}\nevent: text_delta\ndata: {"delta":"a","timelinePartId":"text-1"}\n\n`;
        if (!abrupt || id === 9) return eventStream(event);
        let delivered = false;
        return new Response(
          new ReadableStream({
            pull(controller) {
              if (delivered)
                controller.error(
                  new Error("network interrupted after progress"),
                );
              else {
                delivered = true;
                controller.enqueue(new TextEncoder().encode(event));
              }
            },
          }),
          { headers: { "Content-Type": "text/event-stream" } },
        );
      });
      const completion = expect(
        connectAgentRun(activeRun()),
      ).resolves.toMatchObject({
        status: "completed",
        message: { text: "aaaaaaaa" },
      });
      await vi.runAllTimersAsync();
      await completion;
      expect(cursors).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8]);
    },
  );
  it("bounds premature EOF retries and reconnects after the last acknowledged event", async () => {
    transport.mockImplementation(async () =>
      eventStream(
        transport.mock.calls.length === 1
          ? 'id: 41\nevent: text_delta\ndata: {"delta":"partial","timelinePartId":"timeline-text-1"}\n\n'
          : "",
      ),
    );
    const completion = expect(connectAgentRun(activeRun())).rejects.toThrow(
      /terminal event/i,
    );
    await vi.runAllTimersAsync();
    await completion;
    expect(transport).toHaveBeenCalledTimes(6);
    expect(
      transport.mock.calls
        .slice(1)
        .map(([route]) =>
          new URL(route, "http://agent.test").searchParams.get("after"),
        ),
    ).toEqual(Array(5).fill("41"));
  });
  it("shares one budget between EOF and transport failures and preserves the final error", async () => {
    transport.mockImplementation(async () => {
      const count = transport.mock.calls.length;
      if (count % 2 === 0) throw new Error(`network interruption ${count / 2}`);
      return eventStream();
    });
    const completion = expect(connectAgentRun(activeRun())).rejects.toThrow(
      "network interruption 3",
    );
    await vi.runAllTimersAsync();
    await completion;
    expect(transport).toHaveBeenCalledTimes(6);
  });
  it("publishes one message update per transport chunk and never reconnects after run_done", async () => {
    transport.mockResolvedValue(
      eventStream(
        [
          'id: 7\nevent: text_delta\ndata: {"delta":"done","timelinePartId":"timeline-text-1"}',
          'id: 8\nevent: message_done\ndata: {"message":{"id":"message-done","role":"assistant","text":"done","timeline":[{"id":"timeline-text-1","type":"text","text":"done","toolIds":[]}]}}',
          'id: 9\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}',
          "",
        ].join("\n\n"),
      ),
    );
    const onMessage = vi.fn();
    const result = await connectAgentRun(activeRun(), { onMessage });
    expect(transport).toHaveBeenCalledTimes(1);
    expect(result).toMatchObject({
      status: "completed",
      lastEventId: 9,
      message: {
        text: "done",
        timeline: [
          { id: "timeline-text-1", type: "text", text: "done", toolIds: [] },
        ],
      },
    });
    expect(onMessage).toHaveBeenCalledExactlyOnceWith(result.message);
  });
  it.each([
    {
      name: "cancellation retains partial text",
      prefix: "",
      id: 10,
      text: "kept partial",
      status: "cancelled",
      errorCode: "AGENT_RUN_CANCELLED",
    },
    {
      name: "failed turn retains its rolled-back message",
      prefix:
        'id: 20\nevent: error\ndata: {"error":"Agent model turn limit reached.","errorCode":"AGENT_INTERNAL_ERROR"}\n\n',
      id: 21,
      text: "No unfinished changes were applied.",
      status: "failed",
      errorCode: "AGENT_INTERNAL_ERROR",
    },
  ])("$name", async ({ prefix, id, text, status, errorCode }) => {
    transport.mockResolvedValue(
      eventStream(
        `${prefix}id: ${id}\nevent: message_done\ndata: ${JSON.stringify({ message: { id: "terminal-message", role: "assistant", text, transactionState: "rolled_back" } })}\n\nid: ${id + 1}\nevent: run_done\ndata: ${JSON.stringify({ status, executionState: status, errorCode })}\n\n`,
      ),
    );
    expect(await connectAgentRun(activeRun())).toMatchObject({
      status,
      executionState: status,
      errorCode,
      messageDone: true,
      message: { text, transactionState: "rolled_back" },
    });
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it("posts the streaming request with its signal and invalidates the owning session", async () => {
    const controller = new AbortController();
    const request = {
      message: "Improve the summary",
      resume: { basics: { name: "Test User" } },
      resumeId: "resume-send-test",
    } as unknown as AgentChatRequest;
    transport.mockResolvedValue(
      eventStream(
        'id: 1\nevent: message_done\ndata: {"message":{"id":"message-send-test","text":"done"}}\n\nid: 2\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}\n\n',
        { "X-Agent-Run-Id": "run-send-test" },
      ),
    );
    const result = await sendAgentChatMessage(request, {
      signal: controller.signal,
    });
    expect(transport).toHaveBeenCalledExactlyOnceWith("/api/agent/chat", {
      method: "POST",
      cache: "no-store",
      notifyOnError: false,
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
      },
      signal: controller.signal,
      body: JSON.stringify({ ...request, stream: true }),
    });
    expect(result).toMatchObject({ runId: "run-send-test", messageDone: true });
    expect(clearApiCache).toHaveBeenCalledExactlyOnceWith(
      "/api/agent/resumes/resume-send-test/session",
    );
  });
  it("does not request a subscription whose signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      connectAgentRun(activeRun(), { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(transport).not.toHaveBeenCalled();
  });
});
