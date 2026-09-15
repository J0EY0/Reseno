// @vitest-environment node

import { assert, it, vi } from "vitest";
import { resolveAgentDraftDecision } from "@/lib/agent-session-run-client";
import { createResume } from "./helpers/agent-edit-fixtures";
import type {
  AgentDraftReviewItem,
  AgentSessionResponse,
  AgentResumeEditSuggestion,
} from "@/types/api";

function createAppliedResume() {
  const resume = createResume();
  resume.basic.headline = "Staff Engineer";
  return resume;
}

function createDraftSession(
  status: AgentDraftReviewItem["status"],
  revision: string,
) {
  const baseResume = createResume();
  return {
    resumeId: "resume-draft-decision",
    revision,
    executions: [],
    messages: [
      {
        id: "assistant-draft-decision",
        role: "assistant",
        text: "The edit is ready.",
        createdAt: "2026-08-09T12:00:00.000Z",
        response: {
          id: "assistant-draft-decision",
          role: "assistant",
          text: "The edit is ready.",
          edits: [
            {
              id: "edit-draft-decision",
              title: "Update headline",
              target: "basic.headline",
              reason: "Use the requested title.",
              operation: {
                type: "replace_field",
                path: "basic.headline",
                value: "Staff Engineer",
              },
            },
          ] as AgentResumeEditSuggestion[],
          transactionState: "committed",
          draft: {
            baseResume,
            reviewItems: [
              {
                id: "agent-review-edit-draft-decision",
                editIds: ["edit-draft-decision"],
                status,
              },
            ],
          },
        },
      },
    ],
  } satisfies AgentSessionResponse;
}

function createResumeDetail(
  versionId = "version-formal",
  resumeData = createResume(),
) {
  return {
    resume: {
      id: "resume-draft-decision",
      title: "Draft decision resume",
      updatedAt: "2026-08-09T12:00:00.000Z",
      jobBrief: "",
      typography: { fontFamily: "inter", fontSize: 16 },
      template: "minimal",
      templateSettings: null,
      resume: resumeData,
    },
    savedAt: "2026-08-09T12:00:00.000Z",
    versionId,
  };
}

function apiResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify({ code: 0, data, message: "SUCCESS" }), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function transportError(code: string, details: Record<string, unknown> = {}) {
  return new Response(
    JSON.stringify({ code: 40000, message: code, data: details }),
    {
      headers: { "Content-Type": "application/json" },
      status: 409,
    },
  );
}

async function withDraftDecisionApi(
  responses: Response[],
  unexpectedRequestMessage: string,
  verify: (
    requests: { body: RequestInit["body"]; method: string; url: string }[],
  ) => Promise<void>,
) {
  const authSession = JSON.stringify({
    accessToken: "agent-draft-token",
    expiresAt: "2099-01-01T00:00:00.000Z",
    username: "agent-draft-test",
  });
  const requests: { body: RequestInit["body"]; method: string; url: string }[] =
    [];

  vi.stubGlobal("window", {
    location: { assign() {}, pathname: "/resumes/resume-draft-decision" },
    localStorage: {
      getItem(key: string) {
        return key === "reseno-auth-session" ? authSession : null;
      },
      removeItem() {},
      setItem() {},
    },
    sessionStorage: {
      getItem() {
        return null;
      },
      removeItem() {},
      setItem() {},
    },
  });
  vi.stubGlobal(
    "fetch",
    async (url: RequestInfo | URL, options: RequestInit = {}) => {
      requests.push({
        body: options.body,
        method: options.method ?? "GET",
        url: String(url),
      });
      const response = responses.shift();
      assert(response, unexpectedRequestMessage);
      return response;
    },
  );

  try {
    await verify(requests);
  } finally {
    vi.unstubAllGlobals();
  }
}

it("discards only the selected review scope", async () => {
  const responses = [
    apiResponse(createDraftSession("pending", "revision-discard-pending")),
    apiResponse(createResumeDetail("version-discard-formal")),
    apiResponse({
      session: createDraftSession("discarded", "revision-discarded"),
      resume: null,
    }),
  ];

  await withDraftDecisionApi(
    responses,
    "The draft discard client made an unexpected request.",
    async (requests) => {
      const resolution = await resolveAgentDraftDecision(
        "resume-draft-decision",
        "assistant-draft-decision",
        {
          reviewItemIds: ["agent-review-edit-draft-decision"],
          status: "discarded",
        },
      );

      assert(
        resolution.draft?.reviewItems[0].status === "discarded" &&
          resolution.resume?.versionId === "version-discard-formal" &&
          resolution.committed &&
          resolution.resolvedAsRequested,
        "A discard must resolve the selected item and retain the fresh formal resume.",
      );
      assert(
        requests.length === 3 &&
          requests[2].method === "PATCH" &&
          requests[2].body ===
            JSON.stringify({
              revision: "revision-discard-pending",
              reviewItemIds: ["agent-review-edit-draft-decision"],
              status: "discarded",
            }),
        "A discard must submit only its review-item scope and session revision.",
      );
    },
  );
});

it.each(["applied", "discarded", "superseded"] as const)(
  "reads authoritative terminal status without another write (%j)",
  async (authoritativeStatus) => {
    const responses = [
      apiResponse(
        createDraftSession(authoritativeStatus, "revision-other-tab"),
      ),
      apiResponse(
        createResumeDetail(`version-authoritative-${authoritativeStatus}`),
      ),
    ];

    await withDraftDecisionApi(
      responses,
      "An authoritative apply read made an unexpected request.",
      async (requests) => {
        const resolution = await resolveAgentDraftDecision(
          "resume-draft-decision",
          "assistant-draft-decision",
          {
            currentResume: createResume(),
            currentVersionId: `version-authoritative-${authoritativeStatus}`,
            rebaseOnLatest: true,
            reviewItemIds: ["agent-review-edit-draft-decision"],
            status: "applied",
          },
        );

        assert(
          resolution.draft?.reviewItems[0].status === authoritativeStatus &&
            resolution.resume?.versionId ===
              `version-authoritative-${authoritativeStatus}` &&
            !resolution.committed &&
            resolution.resolvedAsRequested ===
              (authoritativeStatus === "applied"),
          "An already-processed decision must report whether authority matches the requested status.",
        );
        assert(
          requests.length === 2 &&
            requests.every((request) => request.method === "GET"),
          "An already-processed decision must use authoritative reads without issuing PATCH.",
        );
      },
    );
  },
);

it("applies a draft atomically with both current revisions", async () => {
  const responses = [
    apiResponse(createDraftSession("pending", "revision-pending")),
    apiResponse(createResumeDetail()),
    apiResponse({
      session: createDraftSession("applied", "revision-applied"),
      resume: createResumeDetail("version-applied"),
    }),
  ];

  await withDraftDecisionApi(
    responses,
    "The draft decision client made an unexpected request.",
    async (requests) => {
      const resolution = await resolveAgentDraftDecision(
        "resume-draft-decision",
        "assistant-draft-decision",
        {
          currentResume: createResume(),
          currentVersionId: "version-formal",
          rebaseOnLatest: false,
          reviewItemIds: ["agent-review-edit-draft-decision"],
          status: "applied",
        },
      );

      assert(
        resolution.draft?.reviewItems[0].status === "applied" &&
          resolution.session.revision === "revision-applied" &&
          resolution.resume?.versionId === "version-applied" &&
          resolution.committed &&
          resolution.resolvedAsRequested,
        "A successful apply must resolve from the durable assistant response.",
      );
      assert(
        requests.length === 3 &&
          requests[0].method === "GET" &&
          requests[1].method === "GET" &&
          requests[2].method === "PATCH" &&
          requests[2].url.endsWith(
            "/api/agent/resumes/resume-draft-decision/session/messages/assistant-draft-decision/draft",
          ) &&
          requests[2].body ===
            JSON.stringify({
              expectedVersionId: "version-formal",
              revision: "revision-pending",
              reviewItemIds: ["agent-review-edit-draft-decision"],
              resume: createAppliedResume(),
              status: "applied",
            }),
        "A draft apply must atomically submit the candidate with both current revisions.",
      );
    },
  );
});

it("retries one session revision conflict after reloading authority", async () => {
  const responses = [
    apiResponse(createDraftSession("pending", "revision-stale")),
    apiResponse(createResumeDetail()),
    transportError("AGENT_SESSION_REVISION_CONFLICT", {
      revision: "revision-refreshed",
    }),
    apiResponse(createDraftSession("pending", "revision-refreshed")),
    apiResponse(createResumeDetail()),
    apiResponse({
      session: createDraftSession("applied", "revision-reconciled"),
      resume: createResumeDetail("version-reconciled"),
    }),
  ];

  await withDraftDecisionApi(
    responses,
    "Draft decision reconciliation exceeded one retry.",
    async (requests) => {
      const resolution = await resolveAgentDraftDecision(
        "resume-draft-decision",
        "assistant-draft-decision",
        {
          currentResume: createResume(),
          currentVersionId: "version-formal",
          rebaseOnLatest: false,
          reviewItemIds: ["agent-review-edit-draft-decision"],
          status: "applied",
        },
      );

      assert(
        resolution.draft?.reviewItems[0].status === "applied" &&
          resolution.session.revision === "revision-reconciled" &&
          resolution.resume?.versionId === "version-reconciled" &&
          resolution.committed &&
          resolution.resolvedAsRequested,
        "A stale draft decision must converge after one authoritative reload.",
      );
      assert(
        requests.length === 6 &&
          requests[2].body ===
            JSON.stringify({
              expectedVersionId: "version-formal",
              revision: "revision-stale",
              reviewItemIds: ["agent-review-edit-draft-decision"],
              resume: createAppliedResume(),
              status: "applied",
            }) &&
          requests[5].body ===
            JSON.stringify({
              expectedVersionId: "version-formal",
              revision: "revision-refreshed",
              reviewItemIds: ["agent-review-edit-draft-decision"],
              resume: createAppliedResume(),
              status: "applied",
            }),
        "A revision conflict may retry once, using the reloaded session and formal resume.",
      );
    },
  );
});

it("aborts a stale formal version with local changes without retrying", async () => {
  const responses = [
    apiResponse(createDraftSession("pending", "revision-formal-stale")),
    apiResponse(createResumeDetail("version-stale")),
    transportError("RESUME_VERSION_CONFLICT", {
      versionId: "version-current",
    }),
    apiResponse(createDraftSession("pending", "revision-formal-current")),
    apiResponse(createResumeDetail("version-current")),
  ];

  await withDraftDecisionApi(
    responses,
    "A formal-version conflict reconciliation made an unexpected request.",
    async (requests) => {
      let conflictRaised = false;
      try {
        await resolveAgentDraftDecision(
          "resume-draft-decision",
          "assistant-draft-decision",
          {
            currentResume: createResume(),
            currentVersionId: "version-stale",
            rebaseOnLatest: false,
            reviewItemIds: ["agent-review-edit-draft-decision"],
            status: "applied",
          },
        );
      } catch {
        conflictRaised = true;
      }

      assert(
        conflictRaised &&
          requests.length === 5 &&
          requests.filter((request) => request.method === "PATCH").length === 1,
        "A stale formal resume with local edits must reload authority, then abort without an overwrite retry.",
      );
    },
  );
});

it("rebases a clean tab onto a fresh formal resume", async () => {
  const otherTabResume = createResume();
  otherTabResume.basic.summary = "Summary saved by another tab";
  const rebasedResume = createAppliedResume();
  rebasedResume.basic.summary = otherTabResume.basic.summary;
  const responses = [
    apiResponse(createDraftSession("pending", "revision-rebase-stale")),
    apiResponse(createResumeDetail("version-rebase-stale")),
    transportError("RESUME_VERSION_CONFLICT", {
      versionId: "version-rebase-current",
    }),
    apiResponse(createDraftSession("pending", "revision-rebase-current")),
    apiResponse(createResumeDetail("version-rebase-current", otherTabResume)),
    apiResponse({
      session: createDraftSession("applied", "revision-rebase-applied"),
      resume: createResumeDetail("version-rebase-applied", rebasedResume),
    }),
  ];

  await withDraftDecisionApi(
    responses,
    "A safe draft rebase made an unexpected request.",
    async (requests) => {
      const resolution = await resolveAgentDraftDecision(
        "resume-draft-decision",
        "assistant-draft-decision",
        {
          currentResume: createResume(),
          currentVersionId: "version-rebase-stale",
          rebaseOnLatest: true,
          reviewItemIds: ["agent-review-edit-draft-decision"],
          status: "applied",
        },
      );

      assert(
        resolution.resume?.resume.resume.basic.headline === "Staff Engineer" &&
          resolution.resume.resume.resume.basic.summary ===
            "Summary saved by another tab" &&
          resolution.committed &&
          resolution.resolvedAsRequested,
        "A clean tab must rebase its selected item onto another tab's fresh formal resume.",
      );
      assert(
        requests.length === 6 &&
          requests[5].body ===
            JSON.stringify({
              expectedVersionId: "version-rebase-current",
              revision: "revision-rebase-current",
              reviewItemIds: ["agent-review-edit-draft-decision"],
              resume: rebasedResume,
              status: "applied",
            }),
        "A safe retry must rebuild the candidate from the reloaded formal resume.",
      );
    },
  );
});

it.each([
  {
    authoritativeStatus: "applied",
    conflictCode: "AGENT_SESSION_REVISION_CONFLICT",
  },
  {
    authoritativeStatus: "discarded",
    conflictCode: "AGENT_DRAFT_DECISION_CONFLICT",
  },
] as const)(
  "accepts authoritative terminal status after a conflict without retrying (%j)",
  async ({ authoritativeStatus, conflictCode }) => {
    const responses = [
      apiResponse(createDraftSession("pending", "revision-before-terminal")),
      apiResponse(createResumeDetail()),
      transportError(conflictCode, {
        revision: "revision-terminal",
        status: authoritativeStatus,
      }),
      apiResponse(createDraftSession(authoritativeStatus, "revision-terminal")),
      apiResponse(createResumeDetail("version-terminal")),
    ];

    await withDraftDecisionApi(
      responses,
      "A terminal draft reconciliation must not retry.",
      async (requests) => {
        const resolution = await resolveAgentDraftDecision(
          "resume-draft-decision",
          "assistant-draft-decision",
          {
            currentResume: createResume(),
            currentVersionId: "version-formal",
            rebaseOnLatest: false,
            reviewItemIds: ["agent-review-edit-draft-decision"],
            status: "applied",
          },
        );

        assert(
          resolution.draft?.reviewItems[0].status === authoritativeStatus &&
            requests.length === 5 &&
            !resolution.committed &&
            resolution.resolvedAsRequested ===
              (authoritativeStatus === "applied"),
          "After a 409, the authoritative terminal draft status must win without another PATCH.",
        );
      },
    );
  },
);

it.each(
  (["use-original", "keep-manual"] as const).flatMap((resolution) =>
    ["local", "saved", "changed", "raced"].map(
      (scenario) => [scenario, resolution] as const,
    ),
  ),
)(
  "commits explicit whole-draft choices only for the reviewed formal version (%s / %s)",
  async (scenario, conflictResolution) => {
    const currentResume = createResume();
    currentResume.basic.headline = "Reviewed manual headline";
    currentResume.basic.name = "Unrelated manual name";
    const candidate =
      conflictResolution === "use-original"
        ? createAppliedResume()
        : structuredClone(currentResume);
    candidate.basic.summary = "Agent summary";
    const reviewItemIds = [
      "agent-review-edit-draft-decision",
      "agent-review-summary",
    ];
    const createResolutionSession = (
      status: AgentDraftReviewItem["status"],
      revision: string,
    ) => {
      const session = createDraftSession(status, revision);
      const response = session.messages[0].response;
      response.edits.push({
        id: "summary",
        title: "Summary",
        target: "basic.summary",
        reason: "Requested change",
        operation: {
          type: "replace_field",
          path: "basic.summary",
          value: "Agent summary",
        },
      });
      response.draft.reviewItems.push({
        id: "agent-review-summary",
        editIds: ["summary"],
        status,
      });
      return session;
    };
    const changedResume = structuredClone(currentResume);
    changedResume.basic.headline = "Unseen later headline";
    const responses = [
      apiResponse(createResolutionSession("pending", "revision-explicit")),
      apiResponse(
        createResumeDetail(
          scenario === "changed" ? "version-changed" : "version-reviewed",
          scenario === "changed" ? changedResume : currentResume,
        ),
      ),
    ];
    if (scenario === "raced") {
      responses.push(
        transportError("RESUME_VERSION_CONFLICT", {
          versionId: "version-changed",
        }),
        apiResponse(createResolutionSession("pending", "revision-changed")),
        apiResponse(createResumeDetail("version-changed", changedResume)),
      );
    } else if (scenario !== "changed") {
      responses.push(
        apiResponse({
          session: createResolutionSession(
            "applied",
            "revision-explicit-applied",
          ),
          resume: createResumeDetail("version-explicit-applied", candidate),
        }),
      );
    }
    await withDraftDecisionApi(
      responses,
      `Explicit suggestion resolution made an unexpected ${scenario} request.`,
      async (requests) => {
        let resolution;
        let rejected = false;
        try {
          resolution = await resolveAgentDraftDecision(
            "resume-draft-decision",
            "assistant-draft-decision",
            {
              conflictResolution,
              currentResume,
              currentVersionId: "version-reviewed",
              rebaseOnLatest: scenario !== "local",
              reviewItemIds,
              status: "applied",
            },
          );
        } catch {
          rejected = true;
        }
        const writes = requests.filter((request) => request.method === "PATCH");
        if (scenario === "changed" || scenario === "raced") {
          assert(
            rejected &&
              !resolution &&
              writes.length === (scenario === "raced" ? 1 : 0) &&
              requests.length === (scenario === "raced" ? 5 : 2) &&
              responses.length === 0,
            "Explicit conflict resolution must stop when the formal version changes, even when ordinary clean-tab rebasing is allowed.",
          );
        } else {
          assert(
            !rejected &&
              resolution?.committed &&
              resolution.resolvedAsRequested &&
              JSON.stringify(resolution.resume?.resume.resume) ===
                JSON.stringify(candidate) &&
              resolution.draft?.reviewItems.every(
                (item) => item.status === "applied",
              ) &&
              writes.length === 1 &&
              requests.length === 3 &&
              responses.length === 0,
            "Each whole-draft choice must atomically apply its complete candidate and resolve every pending group.",
          );
        }
        if (writes.length > 0) {
          assert(
            writes[0].body ===
              JSON.stringify({
                expectedVersionId: "version-reviewed",
                revision: "revision-explicit",
                reviewItemIds,
                resume: candidate,
                status: "applied",
              }),
            "The explicit decision must commit the selected candidate with its reviewed version through the existing atomic API.",
          );
        }
      },
    );
  },
);
