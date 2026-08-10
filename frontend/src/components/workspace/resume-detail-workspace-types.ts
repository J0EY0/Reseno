import type {
  Dispatch,
  SetStateAction,
} from "react";

import type {
  AgentDraftState,
  AgentDraftSnapshot,
  AgentResumeEditSuggestion,
  AgentTransactionState,
  WorkspaceVersionSummary,
} from "@/types/api";
import type {
  ModelConfig,
  ResumeData,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeTemplateSettings,
  ResumeTypographySettings,
  ResumeWorkspaceItem,
  ThemeMode,
  WorkspaceView,
} from "@/types/resume";

export type ResumeDetailSaveState = "idle" | "saving" | "saved";

export interface ResumeDetailSaveViewState {
  activeVersionId: string | null;
  changeCount: number;
  lastSavedAt: string | null;
  state: ResumeDetailSaveState;
  versions: WorkspaceVersionSummary[];
}

export interface ResumeDetailDocumentViewState {
  isPreviewReady: boolean;
  isSmartFittingOnePage: boolean;
}

export interface ResumeDetailTitleViewState {
  draft: string;
  isOpen: boolean;
}

export interface ResumeDetailLeaveViewState {
  isOpen: boolean;
  isResolving: boolean;
}

export interface ResumeDetailAgentViewState {
  draft: AgentDraftState | null;
  draftState: AgentDraftState | null;
  isPanelCollapsed: boolean;
  modelConfigs: ModelConfig[];
  selectedModelId: string;
}

export interface ResumeDetailWorkspaceState {
  activeTemplate: ResumeTemplateDefinition;
  agent: ResumeDetailAgentViewState;
  collapsedState: Record<string, boolean>;
  document: ResumeDetailDocumentViewState;
  hasLoadError: boolean;
  hasVersionLoadError: boolean;
  hasTemplateStyleOverrides: boolean;
  isDuplicatingResume: boolean;
  isExporting: boolean;
  isLoading: boolean;
  leave: ResumeDetailLeaveViewState;
  previewResume: ResumeData;
  resolvedTheme: "light" | "dark";
  resume: ResumeData;
  resumeItem: ResumeWorkspaceItem | null;
  save: ResumeDetailSaveViewState;
  showSkeleton: boolean;
  template: ResumeTemplateId;
  templates: ResumeTemplateDefinition[];
  theme: ThemeMode;
  title: ResumeDetailTitleViewState;
  typography: ResumeTypographySettings;
}

export interface ResumeDetailAgentCommands {
  applyDraft: () => void;
  changeSelectedModel: (modelId: string) => void;
  discardDraft: () => void;
  flushUserSettings: () => Promise<void>;
  openModelSettings: () => void;
  previewEdits: (
    edits: AgentResumeEditSuggestion[],
    baseResume: ResumeData,
    sourceMessageId?: string,
    transactionState?: AgentTransactionState,
  ) => void;
  reconcileDraft: (snapshot: AgentDraftSnapshot | null) => void;
  rollbackDraft: (sourceMessageId?: string) => void;
  setPanelCollapsed: (collapsed: boolean) => void;
}

export interface ResumeDetailWorkspaceCommands {
  agent: ResumeDetailAgentCommands;
  applyTemplate: (templateId: string) => void;
  back: () => void;
  changeTheme: (theme: ThemeMode) => void;
  changeTitleDraft: (value: string) => void;
  changeView: (view: WorkspaceView) => void;
  duplicateResume: () => void | Promise<void>;
  exportImages: () => void | Promise<void>;
  exportJson: () => void | Promise<void>;
  exportPdf: () => void | Promise<void>;
  fitOnePage: () => void | Promise<void>;
  logout: () => void;
  onPreviewReadyChange: (ready: boolean) => void;
  preloadView: (view: WorkspaceView) => void;
  restoreTemplateDefaults: () => void;
  retryLoad: () => void;
  save: () => void | Promise<unknown>;
  saveTitle: () => void | Promise<void>;
  selectVersion: (versionId: string) => void;
  setCollapsedState: Dispatch<
    SetStateAction<Record<string, boolean>>
  >;
  setResume: Dispatch<SetStateAction<ResumeData>>;
  setTitleDialogOpen: (open: boolean) => void;
  updateTemplateSettings: (
    patch: Partial<ResumeTemplateSettings>,
  ) => void;
  updateTypography: (typography: ResumeTypographySettings) => void;
  cancelLeave: () => void;
  discardAndLeave: () => void | Promise<void>;
  saveAndLeave: () => void | Promise<void>;
}

/** Pure render contract; persistence and route races remain controller-owned. */
export interface ResumeDetailWorkspaceModel {
  commands: ResumeDetailWorkspaceCommands;
  state: ResumeDetailWorkspaceState;
}
