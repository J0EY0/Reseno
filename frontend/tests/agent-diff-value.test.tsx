// @vitest-environment node
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentChangeSummary } from "@/components/copilot/copilot-change-summary";
import {
  AgentDraftReviewDock,
  type AgentDraftReviewDockView,
} from "@/components/copilot/agent-draft-review-dock";
import en from "@/i18n/locales/en.json";
import {
  compactResumeDraftDiffs,
  formatAgentDiffValue,
} from "@/lib/agent-diff-value";
import { createEmptyResume, getInitials } from "@/lib/resume";
import { getInlineTextHtml, getRichTextPlainText } from "@/lib/rich-text";
import type {
  AgentDraftReviewItem,
  AgentResumeEditSuggestion,
  AgentToolInvocation,
} from "@/types/api";
import type { ResumeDraftDiff } from "@/types/resume";

function diff(
  id: string,
  path: string,
  values: Partial<ResumeDraftDiff>,
): ResumeDraftDiff {
  return {
    id,
    operationId: `edit-${id}`,
    label: id,
    kind: "modified",
    path,
    ...values,
  };
}

const messages = {
  ...en,
  agentApplyRemaining: "Apply remaining",
  agentDiscardRemaining: "Discard remaining",
  agentReviewSingleMode: "Single preview",
  agentQualityWarnings: "{count} warnings",
  agentQualityTargetCoverage: "Target coverage",
  agentQualityUnsupportedClaim: "Unsupported claim",
};
const multiFieldEdit: AgentResumeEditSuggestion = {
  id: "edit-project-1",
  title: "Refine project",
  target: "sections.project.items.project-1",
  reason: "Make the project more concise",
  operation: {
    type: "update_item",
    sectionId: "project",
    itemId: "project-1",
    patch: {
      description: "Built an AI resume editor with live preview.",
      highlights: ["Reduced state complexity"],
    },
  },
  diffs: (
    [
      [
        "description",
        "Project Description",
        "Built an AI resume editor with real-time preview.",
        "Built an AI resume editor with live preview.",
      ],
      [
        "highlights",
        "Project Highlights",
        ["Reduced state complexity", "Improved interaction details"],
        ["Reduced state complexity"],
      ],
      ["period", "Project Period", "2026.03 - present", "2026.03 - present"],
    ] as const
  ).map(([field, label, before, after]) =>
    diff(
      `agent-diff-edit-project-1-${field}`,
      `sections.project.items.project-1.${field}`,
      {
        operationId: "edit-project-1",
        label,
        sectionId: "project",
        itemId: "project-1",
        before,
        after,
      },
    ),
  ),
};

function renderSummary(
  statuses: AgentDraftReviewItem["status"][],
  tools: AgentToolInvocation[] = [],
) {
  const edits = statuses.map((_, index) => ({
    ...multiFieldEdit,
    id: `edit-${index}`,
    diffs: multiFieldEdit.diffs?.map((value) => ({
      ...value,
      id: `${value.id}-${index}`,
      operationId: `edit-${index}`,
    })),
  }));
  return renderToStaticMarkup(
    <AgentChangeSummary
      t={messages}
      response={{
        id: "assistant-1",
        role: "assistant",
        text: "Updated the resume.",
        transactionState: "committed",
        edits,
        tools,
        draft: {
          baseResume: createEmptyResume(),
          reviewItems: statuses.map((status, index) => ({
            id: `review-${index}`,
            editIds: [edits[index].id],
            status,
          })),
        },
      }}
    />,
  );
}

function renderDock(patch: Partial<AgentDraftReviewDockView> = {}) {
  const noop = () => undefined;
  return renderToStaticMarkup(
    <AgentDraftReviewDock
      t={messages}
      view={{
        conflicts: [],
        hasScopeConflicts: false,
        disabled: false,
        mode: "all",
        pendingCount: 5,
        resolvingStatus: null,
        selectedIndex: -1,
        onApply: noop,
        onApplyOriginal: noop,
        onKeepManual: noop,
        onDiscard: noop,
        onNext: noop,
        onPrevious: noop,
        onSelectFirst: noop,
        onShowAll: noop,
        ...patch,
      }}
    />,
  );
}

function buttonMarkup(markup: string, label: string) {
  const button = markup.match(
    new RegExp(`<button[^>]*aria-label="${label}"[^>]*>`),
  )?.[0];
  expect(button).toBeDefined();
  return button!;
}

describe("Diff value presentation", () => {
  it.each([
    ["R&D <Component>", "R&amp;D &lt;Component&gt;"],
    ["<strong>literal</strong>", "&lt;strong&gt;literal&lt;/strong&gt;"],
  ])("escapes literal inline text %s", (input, expected) => {
    expect(getInlineTextHtml(input)).toBe(expected);
  });

  it("extracts visible script text and initials from rich text", () => {
    expect(getRichTextPlainText("<p>H<sub>2</sub>O x<sup>2</sup></p>")).toBe(
      "H2O x2",
    );
    expect(getInitials("<p><strong>Ada</strong> Lovelace</p>")).toBe("AL");
  });

  it.each<[unknown, string]>([
    ["<p><sup>Lead</sup> <sub>Engineer</sub></p>", "Lead Engineer"],
    ["", "—"],
    [[], "—"],
    [{ highlights: [] }, "highlights: —"],
    [{ description: "" }, "description: —"],
    [{ content: "English · CET-6" }, "content: English · CET-6"],
    [
      "Use <Component> here; do not rewrite it.",
      "Use <Component> here; do not rewrite it.",
    ],
    [
      "Explain the literal <strong>text</strong> markup to the user.",
      "Explain the literal <strong>text</strong> markup to the user.",
    ],
    [
      "<p>literal but mismatched</strong>",
      "<p>literal but mismatched</strong>",
    ],
    ["<ol><li>First</li><li>Second</li></ol>", "1. First\n2. Second"],
    ["<ul><li>R&amp;D &lt;AI&gt;</li></ul>", "• R&D <AI>"],
    ["<p>&#39;single&#x27; &#160;space</p>", "'single' space"],
    [
      "<p><strong>React</strong> and <em>TypeScript</em></p>",
      "React and TypeScript",
    ],
    ["<div>Intro<p>Alpha</p><p>Beta</p></div>", "Intro\nAlpha\nBeta"],
    [
      "<ul><li>Frontend<ul><li>React</li><li>TypeScript</li></ul></li><li>Backend</li></ul>",
      "• Frontend\n  • React\n  • TypeScript\n• Backend",
    ],
    [["<ul></ul>"], "—"],
    [["<ul><li>React</li><li>TypeScript</li></ul>"], "• React\n• TypeScript"],
    [["<p>React</p>", "TypeScript"], "• React\n• TypeScript"],
  ])("formats %j as visible text", (input, expected) => {
    expect(formatAgentDiffValue(input)).toBe(expected);
  });

  it("includes all visible item fields while hiding internal IDs", () => {
    const fields = {
      name: "Reseno",
      role: "Frontend engineer",
      techStack: ["React", "TypeScript", "Tailwind CSS"],
      period: "2025–2026",
      url: "https://example.com",
      description: "AI resume workspace",
      highlights: ["Built the editor", "Added agent workflows"],
    };
    const value = formatAgentDiffValue({ id: "project-1", ...fields });
    for (const expected of Object.values(fields).flat())
      expect(value).toContain(expected);
    expect(value).not.toContain("project-1");
  });

  it("formats arbitrary nested rich text without mutating its source", () => {
    const value = { arbitraryPayload: "<ul><li>Visible value</li></ul>" };
    const snapshot = structuredClone(value);
    expect(formatAgentDiffValue(value)).toContain(
      "arbitraryPayload: • Visible value",
    );
    expect(value).toEqual(snapshot);
  });

  it("removes unsafe embedded HTML while preserving visible content", () => {
    const value = formatAgentDiffValue(
      '<ul><li><img src="x" onerror="alert(1)"><svg/onload=alert(2)><!--hidden-->Visible<script>alert(3)</script></li></ul>',
    );
    expect(value).not.toMatch(/<img|<svg|onerror|<!--|<script/i);
    expect(value).toContain("Visible");
  });
});

describe("Draft receipts", () => {
  it.each<AgentDraftReviewItem["status"][]>([
    ["pending"],
    ["superseded", "pending"],
  ])("keeps unresolved review controls out of history: %j", (...statuses) => {
    expect(renderSummary(statuses)).toBe("");
  });
  it.each<{
    statuses: AgentDraftReviewItem["status"][];
    text: string;
    absent: RegExp;
  }>([
    {
      statuses: ["applied", "applied", "discarded"],
      text: "Applied 2, discarded 1",
      absent: /Apply draft|Discard draft|role="group"/,
    },
    {
      statuses: ["superseded", "superseded"],
      text: "Replaced by later suggestions",
      absent: /Applied|[Dd]iscarded/,
    },
    {
      statuses: ["applied", "discarded", "superseded", "superseded"],
      text: "Applied 1 · Discarded 1 · 2 replaced by later suggestions",
      absent: /[Dd]iscarded 3|truncate/,
    },
    {
      statuses: ["applied", "superseded"],
      text: "Applied 1 · 1 replaced by later suggestions",
      absent: /[Dd]iscarded/,
    },
    {
      statuses: ["discarded", "superseded"],
      text: "Discarded 1 · 1 replaced by later suggestions",
      absent: /Applied/,
    },
  ])("shows the resolved receipt: $text", ({ statuses, text, absent }) => {
    const markup = renderSummary(statuses);
    expect(markup).toContain('data-slot="agent-draft-resolution-receipt"');
    expect(markup).toContain(text);
    expect(markup).not.toMatch(absent);
  });
  it("keeps localized quality warnings visible while review is pending", () => {
    const markup = renderSummary(
      ["pending"],
      [
        {
          id: "quality",
          type: "resume_validation",
          title: "Quality review",
          state: "output-available",
          output: {
            qualityIssues: [
              {
                code: "target_requirements_not_covered",
                severity: "warning",
                target: "resume",
              },
              {
                code: "unsupported_edit_claim",
                severity: "warning",
                target: "sections.project.items.project-1",
              },
            ],
          },
        },
      ],
    );
    for (const text of ["2 warnings", "Target coverage", "Unsupported claim"])
      expect(markup).toContain(text);
    expect(markup).not.toContain("target_requirements_not_covered");
  });
});

describe("Draft review dock", () => {
  it("shows all remaining changes in the compact horizontal dock", () => {
    const markup = renderDock();
    for (const text of [
      "5 remaining",
      'data-orientation="horizontal"',
      "Apply remaining",
      "Discard remaining",
      'aria-label="Review one by one"',
    ])
      expect(markup).toContain(text);
    expect(markup).not.toMatch(/data-variant="(?:default|outline)"/);
  });
  it.each([true, false])(
    "blocks applying only when the current scope has conflicts: %s",
    (hasScopeConflicts) => {
      const markup = renderDock({
        conflicts: [{ reviewItemId: "review-1", diffs: [] }],
        hasScopeConflicts,
        mode: hasScopeConflicts ? "all" : "single",
        pendingCount: 2,
        selectedIndex: hasScopeConflicts ? -1 : 1,
      });
      expect(markup).toContain("Resolve draft conflicts");
      const apply = buttonMarkup(
        markup,
        hasScopeConflicts ? "Apply remaining" : "Apply this change",
      );
      expect(apply.includes('disabled=""')).toBe(hasScopeConflicts);
      if (hasScopeConflicts) {
        expect(markup).toContain("Your edits are preserved");
        for (const label of ["Discard remaining", "Review one by one"])
          expect(buttonMarkup(markup, label)).not.toMatch(/disabled=/);
      }
    },
  );
  it("shows the selected position and disables decisions during application", () => {
    const markup = renderDock({
      mode: "single",
      pendingCount: 4,
      resolvingStatus: "applied",
      selectedIndex: 1,
    });
    for (const text of [
      "2 of 4",
      "Single preview",
      "Apply this change",
      "Discard this change",
      'aria-label="Applying change"',
      'disabled=""',
    ])
      expect(markup).toContain(text);
  });
});

const insertedProject = {
  id: "project-new",
  name: "Reseno",
  description: "Initial description",
  highlights: [],
};
const updatedProject = {
  ...insertedProject,
  description: "Updated description",
};
const originalExperience = {
  id: "experience-existing",
  kind: "experience",
  title: "Experience",
  items: [
    {
      id: "job-existing",
      company: "Acme",
      position: "Engineer",
      location: "Remote",
      period: "2024–2026",
      description: "Original description",
      highlights: [],
    },
  ],
};

describe("Net draft changes", () => {
  it("removes a field restored to its original value", () => {
    expect(
      compactResumeDraftDiffs([
        diff("summary-1", "basic.summary", { before: "A", after: "B" }),
        diff("summary-2", "basic.summary", { before: "B", after: "A" }),
      ]),
    ).toEqual([]);
  });
  it("removes an item inserted, updated and deleted in the same draft", () => {
    const target = { sectionId: "project", itemId: "project-new" };
    const path = "sections.project.items.project-new";
    expect(
      compactResumeDraftDiffs([
        diff("insert-project", path, {
          ...target,
          kind: "added",
          after: insertedProject,
        }),
        diff("update-project", `${path}.description`, {
          ...target,
          before: "Initial description",
          after: "Updated description",
        }),
        diff("delete-project", path, {
          ...target,
          kind: "deleted",
          before: updatedProject,
        }),
      ]),
    ).toEqual([]);
  });
  it("rewinds edits when deleting an existing item", () => {
    const original = {
      id: "project-existing",
      name: "Existing project",
      description: "Original description",
      highlights: [],
    };
    const target = { sectionId: "project", itemId: original.id };
    const path = `sections.project.items.${original.id}`;
    const removed = diff("delete-existing", path, {
      ...target,
      kind: "deleted",
      before: { ...original, description: "Revised description" },
    });
    expect(
      compactResumeDraftDiffs([
        diff("revise-existing", `${path}.description`, {
          ...target,
          before: "Original description",
          after: "Revised description",
        }),
        removed,
      ]),
    ).toEqual([{ ...removed, before: original }]);
  });
  it("folds an inserted item's updates into its final snapshot", () => {
    const target = { sectionId: "project", itemId: "project-new" };
    const path = "sections.project.items.project-new";
    const added = diff("add-project", path, {
      ...target,
      kind: "added",
      after: insertedProject,
    });
    expect(
      compactResumeDraftDiffs([
        added,
        diff("update-added-project", `${path}.description`, {
          ...target,
          before: "Initial description",
          after: "Updated description",
        }),
      ]),
    ).toEqual([{ ...added, after: updatedProject }]);
  });
  it("rewinds item field changes when deleting their section", () => {
    const path = "sections.experience-existing";
    const removed = diff("delete-experience", path, {
      sectionId: originalExperience.id,
      kind: "deleted",
      before: {
        ...originalExperience,
        items: [
          {
            ...originalExperience.items[0],
            description: "Revised description",
          },
        ],
      },
    });
    expect(
      compactResumeDraftDiffs([
        diff(
          "revise-experience-item",
          `${path}.items.job-existing.description`,
          {
            sectionId: originalExperience.id,
            itemId: "job-existing",
            before: "Original description",
            after: "Revised description",
          },
        ),
        removed,
      ]),
    ).toEqual([{ ...removed, before: originalExperience }]);
  });
  it.each([
    ["experience-new", "job-new", "Updated after insertion"],
    ["experience.archive", "job.v2", "Updated dotted item"],
  ])(
    "folds nested updates without splitting section %s or item %s IDs",
    (sectionId, itemId, description) => {
      const section = {
        ...originalExperience,
        id: sectionId,
        items: [{ ...originalExperience.items[0], id: itemId }],
      };
      const path = `sections.${sectionId}`;
      const added = diff("add-section", path, {
        sectionId,
        kind: "added",
        after: section,
      });
      expect(
        compactResumeDraftDiffs([
          added,
          diff("update-nested-item", `${path}.items.${itemId}.description`, {
            sectionId,
            itemId,
            before: "Original description",
            after: description,
          }),
        ]),
      ).toEqual([
        {
          ...added,
          after: { ...section, items: [{ ...section.items[0], description }] },
        },
      ]);
    },
  );
  it("rewinds a reorder without replacing item objects with IDs", () => {
    const section = {
      ...originalExperience,
      id: "experience-reorder",
      items: [
        { ...originalExperience.items[0], id: "job-a", company: "Alpha" },
        { ...originalExperience.items[0], id: "job-b", company: "Beta" },
      ],
    };
    const path = `sections.${section.id}`;
    const removed = diff("delete-reordered", path, {
      sectionId: section.id,
      kind: "deleted",
      before: { ...section, items: [section.items[1], section.items[0]] },
    });
    expect(
      compactResumeDraftDiffs([
        diff("reorder-items", `${path}.items`, {
          sectionId: section.id,
          kind: "moved",
          before: ["job-a", "job-b"],
          after: ["job-b", "job-a"],
        }),
        removed,
      ]),
    ).toEqual([{ ...removed, before: section }]);
  });
  it("keeps distinct canonical targets whose serialized paths collide", () => {
    const path = "sections.team.items.role";
    const changes = [
      diff("add-colliding-section", path, {
        sectionId: "team.items.role",
        kind: "added",
        after: { ...originalExperience, id: "team.items.role", items: [] },
      }),
      diff("add-colliding-item", path, {
        sectionId: "team",
        itemId: "role",
        kind: "added",
        after: { ...originalExperience.items[0], id: "role" },
      }),
    ];
    expect(compactResumeDraftDiffs(changes)).toEqual(changes);
  });
});
