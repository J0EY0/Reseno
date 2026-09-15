import type { AgentPanelStatus } from "@/components/copilot/copilot-panel-types";
import type { AgentDraftReviewController } from "@/hooks/use-resume-agent-draft";
import type {
  AgentDraftState,
  AgentDraftSnapshot,
  AgentResumeEditSuggestion,
  AgentSessionResponse,
  AgentTransactionState,
  WorkspaceVersionSummary,
} from "@/types/api";
import type {
  ModelConfig,
  ResumeData,
  ResumeSection,
  ResumeDraftDiff,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeTemplateSettings,
  ResumeTypographySettings,
  ResumeWorkspaceItem,
  ThemeMode,
  WorkspaceView,
} from "@/types/resume";

type ResumeDetailSaveState = "idle" | "saving" | "saved";

interface ResumeDetailSaveViewState {
  activeVersionId: string | null;
  changeCount: number;
  lastSavedAt: string | null;
  state: ResumeDetailSaveState;
  versions: WorkspaceVersionSummary[];
}

interface ResumeDetailDocumentViewState {
  isPreviewReady: boolean;
  isSmartFittingOnePage: boolean;
  measurementKey?: object;
}

interface ResumeDetailTitleViewState {
  draft: string;
  isOpen: boolean;
}

interface ResumeDetailLeaveViewState {
  isOpen: boolean;
  isResolving: boolean;
}

interface ResumeDetailAgentViewState {
  draft: AgentDraftState | null;
  draftState: AgentDraftState | null;
  isPanelCollapsed: boolean;
  modelConfigs: ModelConfig[];
  panelStatus: AgentPanelStatus | null;
  review: AgentDraftReviewController | null;
  selectedModelConfigId: string;
}

interface ResumeDetailWorkspaceState {
  activeTemplate: ResumeTemplateDefinition;
  previewTemplate: ResumeTemplateDefinition;
  previewTypography: ResumeTypographySettings;
  agent: ResumeDetailAgentViewState;
  openSectionId: string | null;
  document: ResumeDetailDocumentViewState;
  hasLoadError: boolean;
  hasVersionLoadError: boolean;
  hasTemplateStyleOverrides: boolean;
  isDuplicatingResume: boolean;
  isExporting: boolean;
  isLoading: boolean;
  leave: ResumeDetailLeaveViewState;
  previewResume: ResumeData;
  previewDiffs?: ResumeDraftDiff[];
  previewReview: AgentDraftReviewController | null;
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

interface ResumeDetailAgentCommands {
  applyDraft: () => Promise<AgentSessionResponse | null>;
  changeSelectedModelConfig: (modelConfigId: string) => void;
  discardDraft: () => Promise<AgentSessionResponse | null>;
  flushUserSettings: () => Promise<void>;
  openModelSettings: () => void;
  previewEdits: (
    edits: AgentResumeEditSuggestion[],
    baseResume: ResumeData,
    sourceMessageId?: string,
    transactionState?: AgentTransactionState,
  ) => void;
  reconcileDraft: (snapshot: AgentDraftSnapshot | null) => void;
  reportPanelStatus: (status: AgentPanelStatus) => void;
  rollbackDraft: (sourceMessageId?: string) => void;
  setPanelCollapsed: (collapsed: boolean) => void;
}

interface ResumeDetailWorkspaceCommands {
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
  saveAndReload: (signal?: AbortSignal) => Promise<void>;
  saveTitle: () => void | Promise<void>;
  selectVersion: (versionId: string) => void;
  addSection: (section: ResumeSection) => void;
  removeSection: (sectionId: string) => void;
  toggleSection: (sectionId: string) => void;
  updateContent: (update: (current: ResumeData) => ResumeData) => void;
  setTitleDialogOpen: (open: boolean) => void;
  updateTemplateSettings: (patch: Partial<ResumeTemplateSettings>) => void;
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
