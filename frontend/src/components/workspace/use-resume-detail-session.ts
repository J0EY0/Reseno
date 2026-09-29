import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";

import { createEmptyResume } from "@/lib/resume";
import {
  createResumeEditHistory,
  recordResumeEdit,
  travelResumeHistory,
  type ResumeEditHistory,
} from "@/lib/resume-edit-history";
import { createResumeFingerprint } from "@/lib/workspace-change-tracking";
import type {
  ResumeData,
  ResumeSection,
  ResumeTemplateDefinition,
  ResumeTypographySettings,
  ResumeWorkspaceItem,
} from "@/types/resume";

const defaultTypography: ResumeTypographySettings = {
  fontFamily: "inter",
  fontSize: 16,
};

type ResumeStyle = Pick<ResumeWorkspaceItem, "templateSettings" | "typography">;
type ResumeStyleUpdate =
  Partial<ResumeStyle> | ((current: ResumeStyle) => Partial<ResumeStyle>);

interface ResumeDetailSessionOptions {
  initialResume: ResumeWorkspaceItem | null;
}

/** Owns the editable document and its open editor section. */
export function useResumeDetailSession({
  initialResume,
}: ResumeDetailSessionOptions) {
  const emptyResume = useMemo(() => createEmptyResume(), []);
  const [session, setSession] = useState<
    ResumeEditHistory & {
      openSectionId: string | null;
      sectionNavigation: {
        sectionId: string;
        itemId?: string;
        requestId: number;
      } | null;
    }
  >(() => ({
    ...createResumeEditHistory(initialResume),
    openSectionId: null,
    sectionNavigation: null,
  }));
  const { document, openSectionId, sectionNavigation } = session;
  const fingerprint = useMemo(
    () => createResumeFingerprint(document),
    [document],
  );
  const latestRef = useRef({ document, fingerprint });

  // Saves read the latest committed document after awaiting other requests.
  useLayoutEffect(() => {
    latestRef.current = { document, fingerprint };
  }, [document, fingerprint]);

  const updateDocument = useCallback(
    (
      update: (current: ResumeWorkspaceItem) => ResumeWorkspaceItem,
      historyGroup?: string,
    ) => {
      const editedAt = Date.now();
      setSession((current) => {
        if (!current.document) {
          return current;
        }
        const next = recordResumeEdit(
          current,
          update(current.document),
          editedAt,
          historyGroup,
        );
        return next === current ? current : { ...current, ...next };
      });
    },
    [],
  );

  const hydrate = useCallback((item: ResumeWorkspaceItem) => {
    setSession({
      ...createResumeEditHistory(item),
      openSectionId: null,
      sectionNavigation: null,
    });
  }, []);

  const getSnapshot = useCallback(
    (updatedAt: string): ResumeWorkspaceItem | null => {
      const latest = latestRef.current.document;
      return latest ? { ...latest, updatedAt } : null;
    },
    [],
  );

  const getFingerprint = useCallback(() => latestRef.current.fingerprint, []);

  const adoptSavedResume = useCallback(
    (item: ResumeWorkspaceItem, submitted: ResumeWorkspaceItem) => {
      setSession((current) =>
        current.document?.id === item.id
          ? {
              ...current,
              document: {
                ...current.document,
                title:
                  current.document.title === submitted.title
                    ? item.title
                    : current.document.title,
                updatedAt: item.updatedAt,
              },
            }
          : current,
      );
    },
    [],
  );

  const updateContent = useCallback(
    (
      update: ResumeData | ((current: ResumeData) => ResumeData),
      historyGroup?: string,
    ) => {
      updateDocument((current) => {
        const resume =
          typeof update === "function" ? update(current.resume) : update;
        return resume === current.resume ? current : { ...current, resume };
      }, historyGroup);
    },
    [updateDocument],
  );

  const rename = useCallback(
    (title: string) => {
      const updatedAt = new Date().toISOString();
      updateDocument((current) =>
        title === current.title ? current : { ...current, title, updatedAt },
      );
    },
    [updateDocument],
  );

  const applyTemplate = useCallback(
    (template: ResumeTemplateDefinition) => {
      updateDocument((current) => ({
        ...current,
        template: template.id,
        typography: template.typography,
        templateSettings: template.settings,
      }));
    },
    [updateDocument],
  );

  const updateStyle = useCallback(
    (update: ResumeStyleUpdate, historyGroup?: string) => {
      updateDocument(
        (current) => ({
          ...current,
          ...(typeof update === "function" ? update(current) : update),
        }),
        historyGroup,
      );
    },
    [updateDocument],
  );

  const applyAgentResume = useCallback(
    (resume: ResumeData) => {
      updateDocument((current) => ({ ...current, resume }));
      setSession((current) => ({
        ...current,
        openSectionId: null,
        sectionNavigation: null,
      }));
    },
    [updateDocument],
  );

  const addSection = useCallback(
    (section: ResumeSection) => {
      updateDocument((current) => ({
        ...current,
        resume: {
          ...current.resume,
          sections: [...current.resume.sections, section],
        },
      }));
      setSession((current) =>
        current.document
          ? {
              ...current,
              openSectionId: section.id,
            }
          : current,
      );
    },
    [updateDocument],
  );

  const removeSection = useCallback(
    (id: string) => {
      updateDocument((current) => ({
        ...current,
        resume: {
          ...current.resume,
          sections: current.resume.sections.filter(
            (section) => section.id !== id,
          ),
        },
      }));
      setSession((current) =>
        current.document
          ? {
              ...current,
              openSectionId:
                current.openSectionId === id ? null : current.openSectionId,
            }
          : current,
      );
    },
    [updateDocument],
  );

  const finishHistoryGroup = useCallback(() => {
    setSession((current) =>
      current.group ? { ...current, group: null } : current,
    );
  }, []);

  const travelHistory = useCallback((direction: "undo" | "redo") => {
    setSession((current) => {
      const next = travelResumeHistory(current, direction);
      if (next === current) return current;
      const openSectionId =
        current.openSectionId === "basic" ||
        next.document?.resume.sections.some(
          (section) => section.id === current.openSectionId,
        )
          ? current.openSectionId
          : null;
      return { ...current, ...next, openSectionId, sectionNavigation: null };
    });
  }, []);
  const undo = useCallback(() => travelHistory("undo"), [travelHistory]);
  const redo = useCallback(() => travelHistory("redo"), [travelHistory]);

  const activateSection = useCallback((sectionId: string, itemId?: string) => {
    setSession((current) => {
      const section = current.document?.resume.sections.find(
        (section) => section.id === sectionId,
      );
      if (sectionId !== "basic" && !section) return current;
      if (itemId && !section?.items.some((item) => item.id === itemId))
        return current;
      return {
        ...current,
        openSectionId: sectionId,
        sectionNavigation: {
          sectionId,
          itemId,
          requestId: (current.sectionNavigation?.requestId ?? 0) + 1,
        },
        group: null,
      };
    });
  }, []);

  const toggleSection = useCallback((id: string) => {
    setSession((current) => ({
      ...current,
      openSectionId: current.openSectionId === id ? null : id,
      sectionNavigation: null,
      group: null,
    }));
  }, []);

  return {
    activateSection,
    addSection,
    adoptSavedResume,
    applyAgentResume,
    applyTemplate,
    canUndo: session.past.length > 0,
    canRedo: session.future.length > 0,
    document,
    fingerprint,
    finishHistoryGroup,
    getFingerprint,
    getSnapshot,
    hydrate,
    jobBrief: document?.jobBrief ?? "",
    openSectionId,
    sectionNavigation,
    undo,
    redo,
    removeSection,
    rename,
    resume: document?.resume ?? emptyResume,
    template: document?.template ?? "minimal",
    templateSettings: document?.templateSettings ?? null,
    typography: document?.typography ?? defaultTypography,
    toggleSection,
    updateContent,
    updateStyle,
  };
}

export type ResumeDetailSession = ReturnType<typeof useResumeDetailSession>;
