import {
  useCallback,
  useDeferredValue,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useResumeAgentDraft } from "@/hooks/use-resume-agent-draft";
import type { AppMessages } from "@/i18n";
import type { AgentDraftDecisionResolution } from "@/lib/agent-session-run-client";
import { createEmptyResume } from "@/lib/resume";
import { createResumeFingerprint } from "@/lib/workspace-change-tracking";
import type {
  ResumeData,
  ResumeTemplateId,
  ResumeTemplateSettingsOverrides,
  ResumeTypographySettings,
  ResumeWorkspaceItem,
} from "@/types/resume";

const defaultTypography: ResumeTypographySettings = {
  fontFamily: "inter",
  fontSize: 16,
};

function createCollapsedState(resume: ResumeData, openId?: string) {
  return resume.sections.reduce(
    (state, section) => {
      state[section.id] = section.id !== openId;
      return state;
    },
    { basic: openId !== "basic" } as Record<string, boolean>,
  );
}

interface ResumeDetailSessionOptions {
  initialResume: ResumeWorkspaceItem | null;
  messages: AppMessages;
  onResolveAppliedDraft: (
    messageId: string,
    resume: ResumeData,
  ) => Promise<AgentDraftDecisionResolution>;
}

/** Owns the live document fields and Agent draft, independent of persistence. */
export function useResumeDetailSession({
  initialResume,
  messages,
  onResolveAppliedDraft,
}: ResumeDetailSessionOptions) {
  const emptyResume = useMemo(() => createEmptyResume(), []);
  const [resumeItem, setResumeItem] =
    useState<ResumeWorkspaceItem | null>(initialResume);
  const [resume, setResume] = useState<ResumeData>(
    initialResume?.resume ?? emptyResume,
  );
  const [collapsedState, setCollapsedState] = useState<Record<string, boolean>>(
    () => createCollapsedState(initialResume?.resume ?? emptyResume),
  );
  const [jobBrief, setJobBrief] = useState(initialResume?.jobBrief ?? "");
  const [typography, setTypography] = useState<ResumeTypographySettings>(
    initialResume?.typography ?? defaultTypography,
  );
  const [template, setTemplate] = useState<ResumeTemplateId>(
    initialResume?.template ?? "minimal",
  );
  const [templateSettings, setTemplateSettings] =
    useState<ResumeTemplateSettingsOverrides | null>(
      initialResume?.templateSettings ?? null,
    );

  const applyAgentDraftResume = useCallback((nextResume: ResumeData) => {
    setResume(nextResume);
    setCollapsedState(createCollapsedState(nextResume));
  }, []);
  const agent = useResumeAgentDraft({
    messages,
    onApplyResume: applyAgentDraftResume,
    onResolveAppliedDraft,
    resume,
    resumeId: resumeItem?.id,
  });
  const { agentDraft, resetAgentDraft } = agent;
  const latestRef = useRef({
    agentDraft,
    jobBrief,
    resume,
    resumeItem,
    template,
    templateSettings,
    typography,
  });

  // A stable getter is required after save/discard awaits. Layout sync keeps
  // it current before another browser event or direct route response can run.
  useLayoutEffect(() => {
    latestRef.current = {
      agentDraft,
      jobBrief,
      resume,
      resumeItem,
      template,
      templateSettings,
      typography,
    };
  }, [
    agentDraft,
    jobBrief,
    resume,
    resumeItem,
    template,
    templateSettings,
    typography,
  ]);

  const hydrate = useCallback(
    (item: ResumeWorkspaceItem) => {
      resetAgentDraft();
      setResumeItem(item);
      setResume(item.resume);
      setCollapsedState(createCollapsedState(item.resume));
      setJobBrief(item.jobBrief);
      setTypography(item.typography);
      setTemplate(item.template);
      setTemplateSettings(item.templateSettings);
    },
    [resetAgentDraft],
  );

  const getSnapshot = useCallback(
    (updatedAt: string): ResumeWorkspaceItem | null => {
      const latest = latestRef.current;
      if (!latest.resumeItem) {
        return null;
      }

      return {
        ...latest.resumeItem,
        jobBrief: latest.jobBrief,
        resume: latest.resume,
        template: latest.template,
        templateSettings: latest.templateSettings,
        typography: latest.typography,
        updatedAt,
      };
    },
    [],
  );

  const adoptSavedResume = useCallback(
    (
      item: ResumeWorkspaceItem,
      submitted: ResumeWorkspaceItem,
    ) => {
      setResumeItem((current) =>
        current?.id === item.id
          ? {
              ...current,
              title:
                current.title === submitted.title
                  ? item.title
                  : current.title,
              updatedAt: item.updatedAt,
            }
          : current,
      );
    },
    [],
  );

  const effectiveResume = agentDraft?.resume ?? resume;
  const previewResume = useDeferredValue(effectiveResume);
  const liveResume = resumeItem
    ? {
        ...resumeItem,
        jobBrief,
        resume,
        template,
        templateSettings,
        typography,
      }
    : null;
  const liveFingerprint = createResumeFingerprint(liveResume);
  return {
    ...agent,
    adoptSavedResume,
    collapsedState,
    getSnapshot,
    hydrate,
    jobBrief,
    liveFingerprint,
    liveResume,
    previewResume,
    resume,
    resumeItem,
    setCollapsedState,
    setJobBrief,
    setResume,
    setResumeItem,
    setTemplate,
    setTemplateSettings,
    setTypography,
    template,
    templateSettings,
    typography,
  };
}

export type ResumeDetailSession = ReturnType<typeof useResumeDetailSession>;
