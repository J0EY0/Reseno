import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";

import { createEmptyResume } from "@/lib/resume";
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

type ResumeStyle = Pick<
  ResumeWorkspaceItem,
  "templateSettings" | "typography"
>;
type ResumeStyleUpdate =
  | Partial<ResumeStyle>
  | ((current: ResumeStyle) => Partial<ResumeStyle>);

interface ResumeDetailSessionOptions {
  initialResume: ResumeWorkspaceItem | null;
}

/** Owns the editable document and its open editor section. */
export function useResumeDetailSession({
  initialResume,
}: ResumeDetailSessionOptions) {
  const emptyResume = useMemo(() => createEmptyResume(), []);
  const [{ document, openSectionId }, setSession] = useState<{
    document: ResumeWorkspaceItem | null;
    openSectionId: string | null;
  }>(() => ({ document: initialResume, openSectionId: null }));
  const latestRef = useRef(document);

  // Saves read the latest committed document after awaiting other requests.
  useLayoutEffect(() => {
    latestRef.current = document;
  }, [document]);

  const updateDocument = useCallback(
    (update: (current: ResumeWorkspaceItem) => ResumeWorkspaceItem) => {
      setSession((current) => {
        if (!current.document) {
          return current;
        }
        const next = update(current.document);
        return next === current.document
          ? current
          : { ...current, document: next };
      });
    },
    [],
  );

  const hydrate = useCallback((item: ResumeWorkspaceItem) => {
    setSession({ document: item, openSectionId: null });
  }, []);

  const getSnapshot = useCallback(
    (updatedAt: string): ResumeWorkspaceItem | null => {
      const latest = latestRef.current;
      return latest ? { ...latest, updatedAt } : null;
    },
    [],
  );

  const adoptSavedResume = useCallback(
    (item: ResumeWorkspaceItem, submitted: ResumeWorkspaceItem) => {
      updateDocument((current) =>
        current.id === item.id
          ? {
              ...current,
              title: current.title === submitted.title ? item.title : current.title,
              updatedAt: item.updatedAt,
            }
          : current,
      );
    },
    [updateDocument],
  );

  const updateContent = useCallback(
    (update: ResumeData | ((current: ResumeData) => ResumeData)) => {
      updateDocument((current) => {
        const resume = typeof update === "function" ? update(current.resume) : update;
        return resume === current.resume ? current : { ...current, resume };
      });
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
    (update: ResumeStyleUpdate) => {
      updateDocument((current) => ({
        ...current,
        ...(typeof update === "function" ? update(current) : update),
      }));
    },
    [updateDocument],
  );

  const applyAgentResume = useCallback((resume: ResumeData) => {
    setSession((current) =>
      current.document
        ? {
            document: { ...current.document, resume },
            openSectionId: null,
          }
        : current,
    );
  }, []);

  const addSection = useCallback((section: ResumeSection) => {
    setSession((current) =>
      current.document
        ? {
            document: {
              ...current.document,
              resume: {
                ...current.document.resume,
                sections: [...current.document.resume.sections, section],
              },
            },
            openSectionId: section.id,
          }
        : current,
    );
  }, []);

  const removeSection = useCallback((id: string) => {
    setSession((current) =>
      current.document
        ? {
            document: {
              ...current.document,
              resume: {
                ...current.document.resume,
                sections: current.document.resume.sections.filter(
                  (section) => section.id !== id,
                ),
              },
            },
            openSectionId: current.openSectionId === id ? null : current.openSectionId,
          }
        : current,
    );
  }, []);

  const toggleSection = useCallback((id: string) => {
    setSession((current) => ({
      ...current,
      openSectionId: current.openSectionId === id ? null : id,
    }));
  }, []);

  return {
    addSection,
    adoptSavedResume,
    applyAgentResume,
    applyTemplate,
    document,
    fingerprint: createResumeFingerprint(document),
    getSnapshot,
    hydrate,
    jobBrief: document?.jobBrief ?? "",
    openSectionId,
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
