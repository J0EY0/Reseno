import { render, screen, waitFor, within } from "@testing-library/react";
import { expect, it } from "vitest";

import { createResumeDiffLookup } from "@/components/preview/resume-preview-diff-lookup";
import { SectionItems } from "@/components/preview/resume-preview-section-items";
import { defaultMessages as t } from "@/i18n";
import { projectResumeSection } from "@/lib/resume-sections";
import { createTemplateLayout, createTemplateSettings } from "@/lib/templates";
import type {
  EducationItem,
  ExperienceItem,
  ResumeDraftDiff,
  ResumeSection,
  ResumeTemplateLayout,
  ResumeTimelineItemLayout,
} from "@/types/resume";

function education(overrides: Partial<EducationItem> = {}): ResumeSection {
  return {
    id: "education-section",
    kind: "education",
    title: "Education",
    items: [
      {
        id: "education-item",
        school: "示例大学",
        degree: "硕士",
        major: "软件工程",
        gpa: "3.8 / 4.0",
        location: "深圳",
        period: "2021.09 — 2024.06",
        description: "",
        highlights: [],
        ...overrides,
      },
    ],
  };
}

function experience(overrides: Partial<ExperienceItem> = {}): ResumeSection {
  return {
    id: "experience-section",
    kind: "experience",
    title: "Experience",
    items: [
      {
        id: "experience-item",
        company: "Example Studio",
        position: "Product Engineer",
        location: "Shanghai",
        period: "2024.07 — Present",
        description: "Built a résumé editor.",
        highlights: [],
        ...overrides,
      },
    ],
  };
}

function renderSection(
  section: ResumeSection,
  overrides: Partial<ResumeTemplateLayout> = {},
  diffs: ResumeDraftDiff[] = [],
) {
  const view = render(
    <SectionItems
      section={projectResumeSection(section)}
      layout={createTemplateLayout("minimal", {
        timelineItemLayout: "inline",
        ...overrides,
      })}
      settings={createTemplateSettings("minimal")}
      itemDiffById={createResumeDiffLookup(diffs).itemDiffById}
      t={t}
      enableContactLinks
    />,
  );
  return {
    ...view,
    heading: view.container.querySelector<HTMLElement>(
      "[data-resume-page-block]",
    )!,
  };
}

it("groups the school, degree and major beside the date and keeps metadata below", () => {
  const { heading } = renderSection(education());
  const title = screen.getByRole("heading", { name: "示例大学" });
  const left = title.parentElement!;
  expect(left.querySelector("p")?.textContent).toBe("硕士 · 软件工程");
  expect(left.contains(screen.getByText("2021.09 — 2024.06"))).toBe(false);
  expect(left.contains(screen.getByText("深圳"))).toBe(false);
  expect(heading.contains(left)).toBe(true);
  expect(heading.children[1].textContent).toBe("2021.09 — 2024.06");
  expect(heading.children[2].textContent).toBe("3.8 / 4.0 · 深圳");
});

it("groups the company and position without moving its description into the heading", () => {
  const { heading } = renderSection(experience());
  const title = screen.getByRole("heading", { name: "Example Studio" });
  expect(title.parentElement?.querySelector("p")?.textContent).toBe(
    "Product Engineer",
  );
  expect(heading.children[1].textContent).toBe("2024.07 — Present");
  expect(heading.children[2].textContent).toBe("Shanghai");
  expect(heading.contains(screen.getByText("Built a résumé editor."))).toBe(
    false,
  );
});

it.each([
  ["", "软件工程", "软件工程"],
  ["硕士", "", "硕士"],
  ["", "", ""],
])(
  "omits missing education fields without separators: %s / %s",
  (degree, major, expected) => {
    const { heading } = renderSection(
      education({ degree, major, gpa: "", location: "", period: "" }),
    );
    expect(heading.querySelector("p")?.textContent ?? "").toBe(expected);
    expect(heading.textContent).not.toContain("·");
    expect(heading.children).toHaveLength(1);
  },
);

it("keeps a position visible without an empty company heading", () => {
  const { heading } = renderSection(
    experience({ company: "", location: "", period: "" }),
  );
  expect(within(heading).queryByRole("heading")).toBeNull();
  expect(heading.textContent).toBe("Product Engineer");
});

it.each([
  ["inline", {}, true],
  ["stacked", { education: "inline" }, true],
  ["inline", { education: "stacked" }, false],
  ["stacked", { experience: "inline" }, false],
] satisfies [
  ResumeTimelineItemLayout,
  ResumeTemplateLayout["sectionItemLayouts"],
  boolean,
][])(
  "resolves education layout from global %s and overrides %j",
  (globalLayout, sectionItemLayouts, isInline) => {
    renderSection(education(), {
      timelineItemLayout: globalLayout,
      sectionItemLayouts,
    });
    const title = screen.getByRole("heading", { name: "示例大学" });
    expect(
      title.parentElement?.contains(screen.getByText("2021.09 — 2024.06")),
    ).toBe(!isInline);
  },
);

it("applies an experience override by kind even when the section has a custom id", () => {
  renderSection(
    { ...experience(), id: "custom-work-history" },
    {
      timelineItemLayout: "split",
      sectionItemLayouts: { experience: "inline" },
    },
  );
  const title = screen.getByRole("heading", { name: "Example Studio" });
  expect(title.parentElement?.querySelector("p")?.textContent).toBe(
    "Product Engineer",
  );
});

it("leaves simple-list content independent of timeline layout overrides", () => {
  const { container } = renderSection(
    {
      id: "skills",
      kind: "simple_list",
      title: "Skills",
      items: [{ id: "skills-item", content: "<ul><li>TypeScript</li></ul>" }],
    },
    { listItemLayout: "columns", sectionItemLayouts: { education: "inline" } },
  );
  expect(screen.getByRole("listitem").textContent).toBe("TypeScript");
  expect(
    container
      .querySelector("[data-resume-list-layout]")
      ?.getAttribute("data-resume-list-layout"),
  ).toBe("columns");
  expect(container.querySelector("[data-resume-page-block]")).toBeNull();
});

it("preserves rich-text formatting and separate degree review paths", async () => {
  const path = "sections.education-section.items.education-item.degree";
  const { heading } = renderSection(
    education({
      school: "<p><strong>示例大学</strong></p>",
      degree: "<p><em>硕士</em></p>",
    }),
    {},
    [
      {
        id: "degree-diff",
        operationId: "degree-edit",
        path,
        kind: "modified",
        label: "Change degree",
        sectionId: "education-section",
        itemId: "education-item",
        before: "学士",
        after: "<p><em>硕士</em></p>",
      },
    ],
  );
  expect(heading.querySelector("h3 strong")?.textContent).toBe("示例大学");
  await waitFor(() =>
    expect(
      heading.querySelector(`[data-resume-diff-path="${path}"]`),
    ).not.toBeNull(),
  );
  expect(heading.querySelector("p em")?.textContent).toBe("硕士");
  const major = heading.querySelector('[data-resume-field="major"]')!;
  expect(major.textContent).toBe("软件工程");
  expect(major.querySelector("[data-resume-diff-path]")).toBeNull();
});

it("retains the review anchor for a cleared position without a stray separator", async () => {
  const path = "sections.experience-section.items.experience-item.position";
  const { heading } = renderSection(experience({ position: "" }), {}, [
    {
      id: "position-diff",
      operationId: "position-edit",
      path,
      kind: "modified",
      label: "Clear position",
      sectionId: "experience-section",
      itemId: "experience-item",
      before: "Product Engineer",
      after: "",
    },
  ]);
  await waitFor(() =>
    expect(
      heading.querySelector(`[data-resume-diff-path="${path}"]`),
    ).not.toBeNull(),
  );
  expect(heading.textContent).not.toContain("·");
  expect(heading.textContent).not.toContain("Product Engineer");
});
