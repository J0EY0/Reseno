import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useResumeDetailSession } from "@/components/workspace/use-resume-detail-session";
import { createResumeSection } from "@/lib/resume-sections";
import {
  createResumeDetailItem,
  createResumeDetailTemplate,
} from "./helpers/resume-detail-fixtures";

afterEach(() => vi.useRealTimers());

describe("resume document undo", () => {
  it("restores a complete template switch including the previous custom spacing", () => {
    const initial = createResumeDetailItem({
      templateSettings: { pagePaddingX: 37 },
    });
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: initial }),
    );
    const template = createResumeDetailTemplate("modern");
    act(() => result.current.applyTemplate(template));
    expect(result.current.canUndo).toBe(true);
    act(() => result.current.undo());
    expect(result.current.document).toEqual(initial);
    expect(result.current.canRedo).toBe(true);
    act(() => result.current.redo());
    expect(result.current.template).toBe(template.id);
    expect(result.current.templateSettings).toEqual(template.settings);
  });

  it("groups typing in the same field and breaks the group on focus changes", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: createResumeDetailItem() }),
    );
    const typeName = (name: string) =>
      act(() =>
        result.current.updateContent(
          (resume) => ({ ...resume, basic: { ...resume.basic, name } }),
          "basic:name",
        ),
      );
    typeName("G");
    vi.advanceTimersByTime(100);
    typeName("Grace");
    act(() => result.current.finishHistoryGroup());
    typeName("Grace Hopper");
    act(() => result.current.undo());
    expect(result.current.resume.basic.name).toBe("Grace");
    act(() => result.current.undo());
    expect(result.current.resume.basic.name).toBe("Ada");
    act(() => result.current.redo());
    expect(result.current.resume.basic.name).toBe("Grace");
    typeName("New branch");
    expect(result.current.canRedo).toBe(false);
  });

  it("starts another undo step after a pause and preserves saved server metadata", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: createResumeDetailItem() }),
    );
    act(() =>
      result.current.updateStyle(
        { typography: { fontFamily: "inter", fontSize: 18 } },
        "fontSize",
      ),
    );
    vi.advanceTimersByTime(600);
    act(() =>
      result.current.updateStyle(
        { typography: { fontFamily: "inter", fontSize: 20 } },
        "fontSize",
      ),
    );
    const submitted = result.current.getSnapshot("submitted")!;
    act(() =>
      result.current.adoptSavedResume(
        { ...submitted, updatedAt: "server-time" },
        submitted,
      ),
    );
    act(() => result.current.undo());
    expect(result.current.typography.fontSize).toBe(18);
    expect(result.current.document?.updatedAt).toBe("server-time");
    act(() => result.current.undo());
    expect(result.current.typography.fontSize).toBe(16);
    expect(result.current.canUndo).toBe(false);
  });

  it("records accepted Agent content once and clears history when a document is hydrated", () => {
    const initial = createResumeDetailItem();
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: initial }),
    );
    act(() =>
      result.current.applyAgentResume({
        ...initial.resume,
        basic: { ...initial.resume.basic, name: "Accepted" },
      }),
    );
    act(() => result.current.undo());
    expect(result.current.resume).toEqual(initial.resume);
    act(() =>
      result.current.hydrate(createResumeDetailItem({ id: "another" })),
    );
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("keeps disclosure/navigation and no-op updates out of history", () => {
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: createResumeDetailItem() }),
    );
    act(() => {
      result.current.toggleSection("basic");
      result.current.activateSection("basic");
      result.current.updateContent((resume) => ({ ...resume }));
    });
    expect(result.current.openSectionId).toBe("basic");
    expect(result.current.sectionNavigation?.sectionId).toBe("basic");
    act(() => result.current.activateSection("removed-section"));
    expect(result.current.openSectionId).toBe("basic");
    expect(result.current.canUndo).toBe(false);
  });

  it("targets existing items repeatedly without changing the document or undo history", () => {
    const initial = createResumeDetailItem();
    const section = createResumeSection("experience");
    initial.resume.sections = [section];
    const { result } = renderHook(() =>
      useResumeDetailSession({ initialResume: initial }),
    );
    const itemId = section.items[0].id;
    act(() => result.current.activateSection(section.id, itemId));
    expect(result.current.openSectionId).toBe(section.id);
    expect(result.current.sectionNavigation).toEqual({
      sectionId: section.id,
      itemId,
      requestId: 1,
    });
    act(() => result.current.activateSection(section.id, itemId));
    expect(result.current.sectionNavigation?.requestId).toBe(2);
    act(() => result.current.activateSection(section.id, "missing-item"));
    expect(result.current.sectionNavigation).toEqual({
      sectionId: section.id,
      itemId,
      requestId: 2,
    });
    act(() => result.current.activateSection(section.id));
    expect(result.current.sectionNavigation?.itemId).toBeUndefined();
    expect(result.current.document).toBe(initial);
    expect(result.current.canUndo).toBe(false);
  });
});
