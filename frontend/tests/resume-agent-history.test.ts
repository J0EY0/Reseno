// @vitest-environment node

import type {
  AgentResumeEditSuggestion,
  AgentStoredMessage,
  AgentChatMessage,
} from "@/types/api";
import { assert, it } from "vitest";
import { getAgentDraftSnapshotFromMessages } from "@/lib/agent-draft-review";
import {
  hydrateAgentSession,
  toConversationMessage,
} from "@/components/copilot/copilot-message-model";
import {
  mergeAgentMessage,
  createEmptyAssistantMessage,
} from "@/lib/agent-message-codec";
import { createResume } from "./helpers/agent-edit-fixtures";

it("decodes valid edit statuses and rejects malformed batches atomically", async () => {
  const validEdit: AgentResumeEditSuggestion = {
    id: "explicit-operation",
    title: "Update summary",
    target: "basic.summary",
    reason: "Use the supplied description.",
    operation: {
      type: "replace_field",
      path: "basic.summary",
      value: "New summary",
    },
  };
  for (const status of ["planned", "executed", "rejected"]) {
    const message = mergeAgentMessage(createEmptyAssistantMessage(), {
      edits: [{ ...validEdit, status }],
    });
    assert(
      message.edits![0].status === status &&
        JSON.stringify(message.edits![0].operation) ===
          JSON.stringify(validEdit.operation),
      "Message decoding must retain explicit operations and their review status.",
    );
  }
  for (const operation of [undefined, null, {}]) {
    let rejected = false;
    try {
      mergeAgentMessage(createEmptyAssistantMessage(), {
        edits: [
          validEdit,
          { ...validEdit, id: "invalid-operation", operation },
        ],
      });
    } catch {
      rejected = true;
    }
    assert(
      rejected,
      "Message decoding must reject a malformed edit batch atomically.",
    );
  }
});

it("hydrates durable drafts and preserves terminal review states", async () => {
  const baseResume = createResume();
  const edit: AgentResumeEditSuggestion = {
    id: "durable-edit",
    title: "Update headline",
    target: "basic.headline",
    reason: "Use the requested title.",
    operation: {
      type: "replace_field",
      path: "basic.headline",
      value: "Staff Engineer",
    },
    status: "executed",
    diffs: [
      {
        id: "diff-durable-edit",
        operationId: "durable-edit",
        path: "basic.headline",
        kind: "modified",
        label: "Headline",
        before: "Engineer",
        after: "Staff Engineer",
      },
    ],
  };
  const storedMessages: AgentStoredMessage[] = [
    {
      id: "assistant-durable-draft",
      role: "assistant",
      text: "The edit is ready.",
      createdAt: "2026-08-09T12:00:00.000Z",
      response: {
        id: "assistant-durable-draft",
        role: "assistant",
        text: "The edit is ready.",
        edits: [edit],
        transactionState: "committed",
        draft: {
          baseResume,
          reviewItems: [
            {
              id: "agent-review-durable-edit",
              editIds: ["durable-edit"],
              status: "pending",
            },
          ],
        },
      },
    },
  ];
  const pendingDraft = getAgentDraftSnapshotFromMessages(storedMessages);

  assert(
    pendingDraft?.sourceMessageId === "assistant-durable-draft" &&
      pendingDraft.transactionState === "committed" &&
      pendingDraft.baseResume === baseResume &&
      pendingDraft.edits[0] === edit,
    "Stored messages must retain the committed pending draft and its immutable base.",
  );
  for (const status of ["discarded", "superseded"] as const) {
    const terminalMessages = structuredClone(storedMessages);
    terminalMessages[0].response!.draft!.reviewItems[0].status = status;
    assert(
      getAgentDraftSnapshotFromMessages(terminalMessages)?.reviewItems[0]
        .status === status && getAgentDraftSnapshotFromMessages([]) === null,
      "Authoritative hydration must preserve each terminal draft status and distinguish it from no draft.",
    );
  }

  const hydrated = await hydrateAgentSession(
    Promise.resolve({
      resumeId: "resume-durable-draft",
      revision: "revision-durable-draft",
      messages: storedMessages,
      executions: [],
    }),
  );
  assert(
    hydrated.draftSnapshot?.sourceMessageId === "assistant-durable-draft" &&
      hydrated.draftSnapshot.baseResume === baseResume &&
      hydrated.draftSnapshot.reviewItems[0].status === "pending",
    "The session hydration interface must return the pending draft alongside panel history.",
  );

  const replacementMessage = toConversationMessage(hydrated.panelMessages[0]);
  assert(
    replacementMessage.response?.draft?.reviewItems[0].status === "pending" &&
      replacementMessage.response.draft.baseResume === baseResume &&
      replacementMessage.response.edits?.[0]?.diffs?.[0]?.operationId ===
        "durable-edit",
    "History replacement must preserve the durable draft payload on retained assistant messages.",
  );
});

it("preserves the complete sanitized assistant history during replacement", async () => {
  const storedResponse = {
    id: "assistant-complete-history",
    role: "assistant",
    tone: "success",
    text: "I checked the source and completed the analysis.",
    reasoning: "Concise retained reasoning",
    updates: ["Transient provider status"],
    timeline: [
      {
        id: "timeline-tool-group",
        type: "tool_group",
        toolIds: ["tool-success", "tool-error"],
      },
    ],
    plan: ["Inspect evidence"],
    suggestions: ["Tighten the summary"],
    knowledge: [{ title: "Requirement", detail: "TypeScript" }],
    tools: [
      {
        id: "tool-success",
        type: "tool-web_fetch",
        title: "web_fetch",
        state: "output-available",
        input: { url: "https://example.com/job" },
        output: {
          sourceId: "source-public-job",
          url: "https://example.com/job",
        },
        startedAt: "2026-08-10T10:00:00.000Z",
        completedAt: "2026-08-10T10:00:01.000Z",
      },
      {
        id: "tool-error",
        type: "tool-web_fetch",
        title: "web_fetch",
        state: "output-error",
        input: { url: "https://example.com/job" },
        errorText: "Fetch failed",
        startedAt: "2026-08-10T10:00:02.000Z",
        completedAt: "2026-08-10T10:00:03.000Z",
      },
    ],
    sources: [
      {
        id: "source-public-job",
        title: "Public job description",
        sourceType: "web",
        url: "https://example.com/job",
        excerpt: "Build accessible React and TypeScript products.",
      },
    ],
    transactionState: "none",
  } satisfies AgentChatMessage & Record<string, unknown>;
  const hydrated = await hydrateAgentSession(
    Promise.resolve({
      resumeId: "resume-complete-history",
      revision: "revision-complete-history",
      messages: [
        {
          id: storedResponse.id,
          role: "assistant",
          text: storedResponse.text,
          createdAt: "2026-08-10T10:00:04.000Z",
          response: storedResponse,
        },
      ],
      executions: [],
    }),
  );
  const sanitizedResponse = hydrated.panelMessages[0].response;
  const replacementResponse = toConversationMessage(
    hydrated.panelMessages[0],
  ).response!;

  assert(
    JSON.stringify(replacementResponse) === JSON.stringify(sanitizedResponse) &&
      replacementResponse.sources!.length === 1 &&
      replacementResponse.sources![0].excerpt ===
        "Build accessible React and TypeScript products." &&
      (replacementResponse.tools![0].input as { url: string }).url ===
        "https://example.com/job" &&
      (replacementResponse.tools![0].output as { sourceId: string })
        .sourceId === "source-public-job" &&
      replacementResponse.tools![1].errorText === "Fetch failed" &&
      replacementResponse.tools![1].completedAt === "2026-08-10T10:00:03.000Z",
    "History replacement must preserve the complete sanitized assistant response for PUT-to-GET equivalence.",
  );
});
