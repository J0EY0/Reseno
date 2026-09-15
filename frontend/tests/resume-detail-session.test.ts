import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import { createResumeFingerprint } from "@/lib/workspace-change-tracking";
import type { ResumeSection } from "@/types/resume";

import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

vi.mock("@/lib/workspace-change-tracking", { spy: true });
const tracking = await vi.importActual<
  typeof import("@/lib/workspace-change-tracking")
>("@/lib/workspace-change-tracking");

describe("resume detail session", () => {
  it("applies template defaults and batches edits behind stable committed readers", () => {
    const initial = createResumeDetailItem();
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: initial }),
    );
    const getSnapshot = result.current.getSnapshot;

    const template = createResumeDetailTemplate("modern", {
      name: "Modern",
      updatedAt: initial.updatedAt,
      typography: { fontFamily: "noto_sans_sc", fontSize: 18 },
    });
    template.settings = {
      ...template.settings,
      pagePaddingX: 24,
      pagePaddingTop: 30,
    };
    act(() => result.current.applyTemplate(template));
    expect(result.current.document).toEqual({
      ...initial,
      template: template.id,
      typography: template.typography,
      templateSettings: template.settings,
    });
    act(() => {
      result.current.updateContent((resume) => ({
        ...resume,
        basic: { ...resume.basic, name: "Grace" },
      }));
      result.current.rename("Edited title");
      result.current.updateStyle(({ typography }) => ({
        typography: { ...typography, fontSize: 20 },
      }));
      result.current.updateStyle(({ templateSettings }) => ({
        templateSettings: { ...templateSettings, pagePaddingX: 28 },
      }));
      expect(getSnapshot("before-commit")?.resume.basic.name).toBe("Ada");
    });
    expect(result.current.getSnapshot).toBe(getSnapshot);
    expect(getSnapshot("request-time")).toEqual({
      ...result.current.document,
      updatedAt: "request-time",
    });
    expect(result.current.resume.basic.name).toBe("Grace");
    expect(result.current.document?.title).toBe("Edited title");
    expect(result.current.jobBrief).toBe(initial.jobBrief);
    expect(result.current.template).toBe(template.id);
    expect(result.current.typography).toEqual({
      fontFamily: "noto_sans_sc",
      fontSize: 20,
    });
    expect(result.current.templateSettings).toEqual({
      ...template.settings,
      pagePaddingX: 28,
    });
    expect(result.current.fingerprint).toBe(
      tracking.createResumeFingerprint(result.current.document),
    );
  });

  it("hydrates the committed reader and ignores a previous document's late receipt", () => {
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: createResumeDetailItem() }),
    );
    const getter = result.current.getSnapshot;
    const submitted = getter("submitted")!;
    act(() => result.current.toggleSection("basic"));
    const nextDocument = {
      ...createResumeDetailItem({ id: "resume-b" }),
      title: "Next document",
      jobBrief: "Next job",
    };
    act(() => result.current.hydrate(nextDocument));
    expect(result.current.openSectionId).toBeNull();
    expect(getter("next-time")).toEqual({
      ...nextDocument,
      updatedAt: "next-time",
    });
    act(() =>
      result.current.adoptSavedResume(
        { ...submitted, title: "Old receipt", updatedAt: "late-save" },
        submitted,
      ),
    );
    expect(result.current.document).toEqual(nextDocument);
    expect(result.current.resume).toBe(nextDocument.resume);
    expect(result.current.jobBrief).toBe("Next job");
  });

  it("preserves post-submission edits while adopting saved metadata and untouched titles", () => {
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: createResumeDetailItem() }),
    );
    const submitted = result.current.getSnapshot("submitted")!;
    const newerTypography = {
      fontFamily: "noto_sans_sc",
      fontSize: 20,
    } as const;
    act(() => {
      result.current.updateContent({
        ...submitted.resume,
        basic: { ...submitted.resume.basic, name: "New typing" },
      });
      result.current.rename("New title after submit");
      result.current.updateStyle({
        typography: newerTypography,
        templateSettings: { pagePaddingX: 28 },
      });
    });
    act(() =>
      result.current.adoptSavedResume(
        { ...submitted, title: "Server-normalized title", updatedAt: "saved" },
        submitted,
      ),
    );
    expect(result.current.document?.resume.basic.name).toBe("New typing");
    expect(result.current.document?.title).toBe("New title after submit");
    expect(result.current.document?.typography).toEqual(newerTypography);
    expect(result.current.document?.templateSettings).toEqual({
      pagePaddingX: 28,
    });
    expect(result.current.document?.jobBrief).toBe(submitted.jobBrief);
    expect(result.current.document?.updatedAt).toBe("saved");
    const unchangedTitle = result.current.getSnapshot("submitted-again")!;
    act(() =>
      result.current.adoptSavedResume(
        { ...unchangedTitle, title: "Normalized unchanged title" },
        unchangedTitle,
      ),
    );
    expect(result.current.document?.title).toBe("Normalized unchanged title");
  });

  it("keeps section disclosure separate from queued document and confirmed Agent edits", () => {
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: createResumeDetailItem() }),
    );
    const education: ResumeSection = {
      id: "education",
      kind: "education",
      title: "Education",
      items: [],
    };
    const skills: ResumeSection = {
      id: "skills",
      kind: "simple_list",
      title: "Skills",
      items: [{ id: "skill", content: "" }],
    };
    const fingerprint = result.current.fingerprint;
    act(() => result.current.toggleSection("basic"));
    expect(result.current.openSectionId).toBe("basic");
    expect(result.current.fingerprint).toBe(fingerprint);
    act(() => result.current.toggleSection("basic"));
    expect(result.current.openSectionId).toBeNull();
    act(() => {
      result.current.addSection(education);
      result.current.addSection(skills);
    });
    expect(result.current.resume.sections).toEqual([education, skills]);
    expect(result.current.openSectionId).toBe("skills");
    act(() => result.current.removeSection("education"));
    expect(result.current.openSectionId).toBe("skills");
    act(() => result.current.removeSection("skills"));
    expect(result.current.openSectionId).toBeNull();
    expect(result.current.resume.sections).toEqual([]);
    const applied = {
      ...result.current.resume,
      basic: { ...result.current.resume.basic, name: "Confirmed Agent edit" },
    };
    act(() => {
      result.current.toggleSection("basic");
      result.current.applyAgentResume(applied);
    });
    expect(result.current.resume).toBe(applied);
    expect(result.current.openSectionId).toBeNull();
    expect(result.current.getSnapshot("after-apply")?.resume).toBe(applied);
    expect(result.current.document?.title).toBe("Original title");
    expect(result.current.jobBrief).toBe("Original job brief");
  });

  it("does not fabricate an unloaded document", () => {
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: null }),
    );
    expect(result.current.document).toBeNull();
    expect(result.current.getSnapshot("empty")).toBeNull();
    act(() => {
      result.current.updateContent(createResumeDetailItem().resume);
      result.current.rename("Not loaded");
      result.current.updateStyle({
        typography: { fontFamily: "inter", fontSize: 20 },
      });
    });
    expect(result.current.document).toBeNull();
    act(() => result.current.hydrate(createResumeDetailItem()));
    expect(result.current.getSnapshot("loaded")?.id).toBe("resume-a");
  });

  it("reuses fingerprints through 20 disclosure updates and recomputes once per document edit", () => {
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: createResumeDetailItem() }),
    );
    const before = vi.mocked(createResumeFingerprint).mock.calls.length;
    for (let index = 0; index < 20; index += 1)
      act(() => result.current.toggleSection("basic"));
    expect(createResumeFingerprint).toHaveBeenCalledTimes(before);
    const getFingerprint = result.current.getFingerprint;
    const committedFingerprint = getFingerprint();
    act(() => {
      result.current.rename("Pending title");
      expect(getFingerprint()).toBe(committedFingerprint);
    });
    expect(result.current.getFingerprint).toBe(getFingerprint);
    expect(getFingerprint()).not.toBe(committedFingerprint);
    expect(getFingerprint()).toBe(
      tracking.createResumeFingerprint(result.current.getSnapshot("now")),
    );
    expect(createResumeFingerprint).toHaveBeenCalledTimes(before + 1);
  });
});
