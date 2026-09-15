// @vitest-environment node

import assert from "node:assert/strict";
import { beforeEach, it, vi } from "vitest";
import {
  api,
  enqueueDeferred,
  enqueueEnvelope,
  enqueueJson,
  requests,
  replies,
  testState,
  unauthorizedPayload,
  waitForRequestCount,
} from "./helpers/api-client-fixture";

import { createEmptyResume } from "@/lib/resume";
import type { AgentRunResponse } from "@/types/api";
let streamClient: typeof import("@/lib/agent-stream-client");
let attachmentClient: typeof import("@/lib/agent-attachment-client");
beforeEach(async () => {
  streamClient = await import("@/lib/agent-stream-client");
  attachmentClient = await import("@/lib/agent-attachment-client");
});
const renameRun: AgentRunResponse = {
  id: "run-rename",
  resumeId: "resume-rename",
  baseResume: createEmptyResume(),
  errorCode: null,
  executionState: "running",
  lastEventId: 0,
  status: "active",
};
it("reconnects from the last event after a username change replaces its token", async () => {
  let finishUsernameChange!: () => void;
  testState.refreshPending = new Promise<void>((resolve) => {
    finishUsernameChange = resolve;
  });
  replies.push({
    body: 'id: 7\nevent: text_delta\ndata: {"delta":"partial","timelinePartId":"text-1"}\n\n',
    contentType: "text/event-stream",
    status: 200,
  });
  const staleStreamResponse = enqueueDeferred();
  replies.push({
    body: 'id: 8\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}\n\n',
    contentType: "text/event-stream",
    status: 200,
  });
  const reconnectResult = streamClient.connectAgentRun(renameRun).then(
    (value) => ({ value, error: undefined }),
    (error: unknown) => ({ error, value: undefined }),
  );
  await waitForRequestCount(2);
  assert.equal(requests.length, 2);
  staleStreamResponse.resolveJson(unauthorizedPayload, 401);
  await vi.waitFor(() => assert.equal(testState.lockRequests.length, 1));
  assert.deepEqual(testState.lockRequests, [
    { name: "reseno-auth-refresh", options: { mode: "shared" } },
  ]);
  assert.equal(testState.clearedAuthCount, 0);
  testState.token = "renamed-token";
  finishUsernameChange();
  const reconnectedAfterRename = await reconnectResult;
  assert.equal(testState.token, "renamed-token");
  assert.deepEqual(testState.invalidations, []);
  assert.equal(
    reconnectedAfterRename.error,
    undefined,
    "An SSE reconnect rejected with a replaced token must retry after the username change.",
  );
  assert.ok(reconnectedAfterRename.value);
  assert.equal(reconnectedAfterRename.value.status, "completed");
  assert.equal(reconnectedAfterRename.value.message.text, "partial");
  assert.deepEqual(
    requests.map((request) =>
      new URL(request.url, "http://api.test").searchParams.get("after"),
    ),
    ["0", "7", "7"],
  );
  assert.deepEqual(
    requests.map((request) => request.headers.get("Authorization")),
    ["Bearer token-a", "Bearer token-a", "Bearer renamed-token"],
  );
  assert.deepEqual(testState.toasts, []);
});
it("invalidates an unchanged expired SSE token without retrying", async () => {
  enqueueJson(unauthorizedPayload, 401);
  await assert.rejects(streamClient.connectAgentRun(renameRun), (error) => {
    assert.equal(api.getApiErrorStatus(error), 401);
    return true;
  });
  assert.equal(requests.length, 1);
  assert.equal(testState.token, null);
  assert.equal(testState.clearedAuthCount, 1);
});

it("bounds a subscription to one retry across repeated token replacements", async () => {
  const firstExpiredStream = enqueueDeferred();
  const secondExpiredStream = enqueueDeferred();
  const boundedReconnect = assert.rejects(
    streamClient.connectAgentRun(renameRun),
    (error) => {
      assert.equal(api.getApiErrorStatus(error), 401);
      return true;
    },
  );
  await waitForRequestCount(1);
  testState.token = "token-b";
  firstExpiredStream.resolveJson(unauthorizedPayload, 401);
  await waitForRequestCount(2);
  testState.token = "token-c";
  secondExpiredStream.resolveJson(unauthorizedPayload, 401);
  await boundedReconnect;
  assert.equal(
    requests.length,
    2,
    "One SSE subscription must retry a replaced token only once.",
  );
  assert.equal(testState.token, "token-c");
  assert.deepEqual(testState.invalidations, []);
});

it.each([
  "",
  "https://api.example",
  "https://api.example/proxy",
  "https://api.example/api",
  "/proxy",
  "/api",
])(
  "applies API base %j once to chat, reconnect and attachment URLs",
  async (base) => {
    vi.stubEnv("VITE_API_BASE_URL", base);
    const streamReply = {
      body: 'id: 1\nevent: run_done\ndata: {"status":"completed","executionState":"succeeded"}\n\n',
      contentType: "text/event-stream",
      headers: { "X-Agent-Run-Id": "run-base" },
      status: 200,
    };
    replies.push(streamReply);
    const started = await streamClient.sendAgentChatMessage({
      resumeId: "resume-base",
      resume: createEmptyResume(),
      message: { id: "message-base", role: "user", text: "Hello" },
      messages: [],
      locale: "en",
      modelConfig: null,
    });
    assert.equal(started.status, "completed");
    assert.equal(requests.at(-1)?.url, `${base}/api/agent/chat`);
    assert.equal(requests.at(-1)?.method, "POST");
    replies.push(streamReply);
    const reconnected = await streamClient.connectAgentRun({
      id: "run-base",
      resumeId: "resume-base",
      baseResume: createEmptyResume(),
      errorCode: null,
      executionState: "running",
      lastEventId: 0,
      status: "active",
    });
    assert.equal(reconnected.status, "completed");
    assert.equal(
      requests.at(-1)?.url,
      `${base}/api/agent/runs/run-base/events?after=0`,
    );
    assert.equal(requests.at(-1)?.method, "GET");
    enqueueEnvelope({ attachment: true });
    await attachmentClient.downloadAgentAttachment(
      "resume-base",
      "attachment-base",
    );
    assert.equal(
      requests.at(-1)?.url,
      `${base}/api/agent/resumes/resume-base/attachments/attachment-base`,
    );
    assert.ok(
      requests.every(
        (request) => request.headers.get("Authorization") === "Bearer token-a",
      ),
    );
  },
);
