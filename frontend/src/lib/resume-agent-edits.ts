import type { AgentResumeEditSuggestion } from "@/types/api";
import type { ResumeData, ResumeDraftDiff } from "@/types/resume";
import { applyOperation } from "./resume-agent-edits/apply-operations";
import { applyOperationWithMerge } from "./resume-agent-edits/three-way-merge";
import {
  cloneResume,
  fallbackOperation,
  type AgentDraftApplyError,
  type AgentDraftApplyErrorReason,
  type AgentDraftApplyResult,
} from "./resume-agent-edits/transaction-core";

export type {
  AgentDraftApplyError,
  AgentDraftApplyErrorReason,
  AgentDraftApplyResult,
};

/**
 * Captures the immutable merge base used when an Agent draft is generated.
 * The editor may keep changing before the user applies the draft, so retaining
 * a reference to live state would make a later three-way merge unreliable.
 */
export function createAgentDraftBaseSnapshot(
  baseResume: ResumeData,
): ResumeData {
  return cloneResume(baseResume);
}

export function applyAgentEditsToDraft(
  baseResume: ResumeData,
  edits: AgentResumeEditSuggestion[],
): AgentDraftApplyResult {
  const workingResume = cloneResume(baseResume);
  const diffs: ResumeDraftDiff[] = [];
  const errors: AgentDraftApplyError[] = [];

  edits.forEach((edit) => {
    const operation = fallbackOperation(edit);

    if (!operation) {
      errors.push({
        editId: edit.id,
        title: edit.title || edit.id,
        target: edit.target || edit.id,
        reason: "missing_operation",
      });
      return;
    }

    const result = applyOperation(workingResume, edit, operation);

    if (result.ok) {
      diffs.push(result.diff);
      return;
    }

    errors.push({
      editId: edit.id,
      title: edit.title || edit.id,
      operationType: operation.type,
      target: result.target || edit.target || edit.id,
      reason: result.reason,
    });
  });

  // The working copy is the transaction buffer. It is published only after every
  // operation succeeds, so callers can never preview or apply a partial batch.
  if (errors.length > 0) {
    return {
      resume: cloneResume(baseResume),
      diffs: [],
      appliedCount: 0,
      errors,
    };
  }

  return {
    resume: workingResume,
    diffs,
    appliedCount: diffs.length,
    errors,
  };
}

/**
 * Applies an Agent batch against the resume the user is editing now.
 *
 * The Agent's base snapshot is advanced operation-by-operation beside the
 * current resume. Field edits merge when the user changed a different field;
 * competing field or structural edits reject the complete candidate.
 */
export function applyAgentEditsWithMerge(
  baseResume: ResumeData,
  currentResume: ResumeData,
  edits: AgentResumeEditSuggestion[],
): AgentDraftApplyResult {
  const validation = applyAgentEditsToDraft(baseResume, edits);
  if (validation.errors.length > 0) {
    return { ...validation, resume: cloneResume(currentResume) };
  }

  const baseWorking = cloneResume(baseResume);
  const currentWorking = cloneResume(currentResume);
  const diffs: ResumeDraftDiff[] = [];

  for (const edit of edits) {
    const operation = fallbackOperation(edit);
    if (!operation) {
      // The validation pass above guarantees this cannot happen.
      continue;
    }

    const merged = applyOperationWithMerge(
      baseWorking,
      currentWorking,
      edit,
      operation,
    );

    if (!merged.ok) {
      return {
        resume: cloneResume(currentResume),
        diffs: [],
        appliedCount: 0,
        errors: [{
          editId: edit.id,
          title: edit.title || edit.id,
          operationType: operation.type,
          target: merged.target,
          reason: "conflict",
        }],
      };
    }

    if (merged.diff) {
      diffs.push(merged.diff);
    }

    const baseResult = applyOperation(baseWorking, edit, operation);
    if (!baseResult.ok) {
      return {
        resume: cloneResume(currentResume),
        diffs: [],
        appliedCount: 0,
        errors: [{
          editId: edit.id,
          title: edit.title || edit.id,
          operationType: operation.type,
          target: baseResult.target,
          reason: baseResult.reason,
        }],
      };
    }
  }

  return {
    resume: currentWorking,
    diffs,
    appliedCount: diffs.length,
    errors: [],
  };
}
