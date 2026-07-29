import {
  Bot,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CopyPlus,
  Download,
  FileJson,
  FileText,
  Images,
  Languages,
  LogOut,
  Minimize2,
  Moon,
  Pencil,
  Plus,
  SlidersHorizontal,
  Sun,
} from "lucide-react";
import {
  lazy,
  startTransition,
  Suspense,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ChangeEvent,
} from "react";
import { matchPath, useLocation, useNavigate } from "react-router-dom";

import { AppSidebar } from "@/components/app-sidebar";
import { AppToaster } from "@/components/app-toaster";
import { AvatarCropDialog } from "@/components/editor/avatar-crop-dialog";
import { BasicInfoCard } from "@/components/editor/basic-info-card";
import { ResumeSectionCard } from "@/components/editor/resume-section-card";
import { ResumePreview } from "@/components/preview/resume-preview";
import { SaveStatusButton } from "@/components/save-status-button";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { Spinner } from "@/components/ui/spinner";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ViewTransitionBoundary } from "@/components/view-transition";
import { readAvatarFileAsDataUrl } from "@/lib/avatar";
import { normalizeContactFieldType } from "@/lib/contact-links";
import {
  createDefaultAgentSettings,
  normalizeAgentSettings,
} from "@/lib/agent-settings";
import { isApiErrorToastShown } from "@/lib/api-client";
import {
  downloadExportedFile,
  downloadResumeJson,
  requestResumeImagesExport,
} from "@/lib/export-api";
import {
  applyAgentEditsWithMerge,
  createAgentDraftBaseSnapshot,
  type AgentDraftApplyError,
} from "@/lib/resume-agent-edits";
import {
  importResumePayload,
  importTemplatePayload,
} from "@/lib/import-api";
import { normalizeModelConfigs } from "@/lib/model-config";
import { importResumeFromPdf } from "@/lib/pdf-resume-import";
import { isRichTextEmpty } from "@/lib/rich-text";
import {
  createTemplateSettings,
  createTemplateLayout,
  createCustomTemplateFromBase,
  getResumeFontSizeInPoints,
  getTemplateById,
  getTemplateCatalog,
  normalizeCustomTemplates,
  normalizeDeletedTemplates,
  resumeFontSizeOptions,
} from "@/lib/templates";
import { createTemplatePreviewResume } from "@/lib/template-preview-resume";
import { getMessagesSync, type AppMessages, type Locale } from "@/i18n";
import {
  createEmptyResume,
  createId,
  createItem,
  createSection,
  getKeywordMatch,
} from "@/lib/resume";
import { cn } from "@/lib/utils";
import {
  createTemplateApi,
  createResumeApi,
  deleteResumeForeverApi,
  deleteTemplateForeverApi,
  duplicateResumeApi,
  fetchDeletedTemplatesApi,
  fetchDeletedResumesApi,
  fetchResumeApi,
  fetchResumeVersionApi,
  fetchResumeVersionsApi,
  fetchResumesApi,
  fetchTemplatesApi,
  fetchWorkspaceBootstrap,
  moveTemplateToTrashApi,
  moveResumeToTrashApi,
  restoreTemplateApi,
  restoreResumeApi,
  saveDefaultTemplateApi,
  saveUserSettingsApi,
  saveResumeApi,
  saveTemplateApi,
} from "@/lib/workspace-api";
import { runViewTransition } from "@/lib/view-transition";
import { getWorkspacePath } from "@/lib/workspace-route";
import type {
  AgentDraftState,
  AgentResumeEditSuggestion,
  AgentTransactionState,
  SaveResponse,
  WorkspaceVersionSummary,
} from "@/types/api";
import type {
  AgentSettings,
  CustomField,
  DeletedResumeTemplateDefinition,
  DeletedResumeWorkspaceItem,
  ModelConfig,
  ResumeBasicInfo,
  ResumeData,
  ResumeFontFamily,
  ResumeSection,
  ResumeSectionItem,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeTemplateImageElement,
  ResumeTemplateSettings,
  ResumeTypographySettings,
  ResumeWorkspaceItem,
  SectionKind,
  ThemeMode,
  WorkspaceView,
} from "@/types/resume";
import { toast } from "sonner";

let copilotPanelModulePromise:
  | Promise<typeof import("@/components/copilot/copilot-panel")>
  | null = null;

let recycleBinPanelModulePromise:
  | Promise<typeof import("@/components/recycle-bin-panel")>
  | null = null;
let resumeGalleryModulePromise:
  | Promise<typeof import("@/components/resume-gallery")>
  | null = null;
let modelConfigPanelModulePromise:
  | Promise<typeof import("@/components/model-config-panel")>
  | null = null;
let settingsPanelModulePromise:
  | Promise<typeof import("@/components/settings-panel")>
  | null = null;
let templateLibraryModulePromise:
  | Promise<typeof import("@/components/template-library")>
  | null = null;

function loadCopilotPanelModule() {
  copilotPanelModulePromise ??= import("@/components/copilot/copilot-panel");
  return copilotPanelModulePromise;
}

function loadRecycleBinPanelModule() {
  recycleBinPanelModulePromise ??= import("@/components/recycle-bin-panel");
  return recycleBinPanelModulePromise;
}

function loadResumeGalleryModule() {
  resumeGalleryModulePromise ??= import("@/components/resume-gallery");
  return resumeGalleryModulePromise;
}

function loadModelConfigPanelModule() {
  modelConfigPanelModulePromise ??= import("@/components/model-config-panel");
  return modelConfigPanelModulePromise;
}

function loadSettingsPanelModule() {
  settingsPanelModulePromise ??= import("@/components/settings-panel");
  return settingsPanelModulePromise;
}

function loadTemplateLibraryModule() {
  templateLibraryModulePromise ??= import("@/components/template-library");
  return templateLibraryModulePromise;
}

const CopilotPanel = lazy(() =>
  loadCopilotPanelModule().then((module) => ({
    default: module.CopilotPanel,
  })),
);
const RecycleBinPanel = lazy(() =>
  loadRecycleBinPanelModule().then((module) => ({
    default: module.RecycleBinPanel,
  })),
);
const ResumeGallery = lazy(() =>
  loadResumeGalleryModule().then((module) => ({
    default: module.ResumeGallery,
  })),
);
const ModelConfigPanel = lazy(() =>
  loadModelConfigPanelModule().then((module) => ({
    default: module.ModelConfigPanel,
  })),
);
const SettingsPanel = lazy(() =>
  loadSettingsPanelModule().then((module) => ({
    default: module.SettingsPanel,
  })),
);
const TemplateLibrary = lazy(() =>
  loadTemplateLibraryModule().then((module) => ({
    default: module.TemplateLibrary,
  })),
);

function preloadWorkspaceView(view: WorkspaceView) {
  if (view === "resume") {
    void loadResumeGalleryModule();
    return;
  }

  if (view === "templates") {
    void loadTemplateLibraryModule();
    return;
  }

  if (view === "trash") {
    void loadRecycleBinPanelModule();
    return;
  }

  if (view === "models") {
    void loadModelConfigPanelModule();
    return;
  }

  void loadSettingsPanelModule();
}

function getAgentDraftErrorReason(
  error: AgentDraftApplyError,
  t: AppMessages,
) {
  switch (error.reason) {
    case "missing_operation":
      return t.agentDraftErrorMissingOperation;
    case "invalid_operation":
      return t.agentDraftErrorInvalidOperation;
    case "target_not_found":
      return t.agentDraftErrorTargetNotFound;
    case "duplicate_target":
      return t.agentDraftErrorDuplicateTarget;
    case "no_change":
      return t.agentDraftErrorNoChange;
    case "conflict":
      return t.agentDraftErrorConflict;
  }
}

function formatAgentDraftErrors(
  errors: AgentDraftApplyError[],
  t: AppMessages,
) {
  return errors
    .map((error) => `${error.title}: ${getAgentDraftErrorReason(error, t)}`)
    .join(" · ");
}

const defaultTypography: ResumeTypographySettings = {
  fontFamily: "inter",
  fontSize: 16,
};

const defaultTemplate: ResumeTemplateId = "minimal";
const A4_WIDTH_PX = (210 / 25.4) * 96;
const A4_HEIGHT_PX = (297 / 25.4) * 96;
const PREVIEW_FRAME_GUTTER_PX = 48;
const MAX_RESUME_TITLE_LENGTH = 20;
// Keep this aligned with the 2xl workspace breakpoint in index.css. Below it,
// the Agent uses a Sheet so the editor and preview retain usable widths.
const AGENT_DOCK_MEDIA_QUERY = "(min-width: 1536px)";
const SMART_ONE_PAGE_MAX_PAGE_COUNT = 1;
const SMART_ONE_PAGE_MIN_FONT_SIZE = 12;
const SMART_ONE_PAGE_LAYOUT_LEVELS = [
  {
    pagePaddingDelta: 2,
    sectionGap: 1,
    itemGap: 0.7,
    bodyLineHeight: 1.55,
  },
  {
    pagePaddingDelta: 3,
    sectionGap: 0.9,
    itemGap: 0.6,
    bodyLineHeight: 1.48,
    sectionTitleScale: 1.12,
  },
  {
    pagePaddingDelta: 4,
    sectionGap: 0.8,
    itemGap: 0.5,
    bodyLineHeight: 1.42,
    sectionTitleScale: 1,
    itemTitleScale: 0.96,
    metaScale: 0.86,
  },
  {
    pagePaddingDelta: 5,
    sectionGap: 0.8,
    itemGap: 0.4,
    bodyLineHeight: 1.4,
    nameScale: 1.85,
    sectionTitleScale: 0.9,
    itemTitleScale: 0.92,
    metaScale: 0.82,
    bodyScale: 0.9,
  },
] satisfies Array<{
  pagePaddingDelta: number;
  sectionGap: number;
  itemGap: number;
  bodyLineHeight: number;
  nameScale?: number;
  sectionTitleScale?: number;
  itemTitleScale?: number;
  metaScale?: number;
  bodyScale?: number;
}>;

type SmartOnePageStyleSnapshot = {
  typography: ResumeTypographySettings;
  templateSettings: ResumeTemplateSettings | null;
};

function WorkspacePanelSkeleton() {
  return (
    <div className="grid gap-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <Card
          key={index}
          className="rounded-2xl border-border/80 bg-card shadow-sm"
        >
          <CardContent className="space-y-4 p-5">
            <div className="flex items-center gap-3">
              <Skeleton className="size-11 rounded-2xl" />
              <div className="grid flex-1 gap-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-48" />
              </div>
              <Skeleton className="size-9 rounded-xl" />
            </div>
            {index === 0 ? (
              <div className="grid gap-3 sm:grid-cols-[160px_minmax(0,1fr)]">
                <Skeleton className="h-36 rounded-2xl" />
                <div className="grid gap-3">
                  <Skeleton className="h-10 rounded-xl" />
                  <Skeleton className="h-10 rounded-xl" />
                  <Skeleton className="h-10 rounded-xl" />
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function WorkspacePreviewSkeleton() {
  return (
    <section className="resume-preview-card relative flex min-w-0 flex-col overflow-hidden rounded-(--radius-preview) border border-border bg-card p-4 xl:self-start">
      <div className="mb-4">
        <Skeleton className="h-3 w-24" />
      </div>
      <div className="flex justify-center">
        <div className="w-[min(100%,640px)] rounded-(--radius-card) border border-border bg-background p-10 shadow-[0_18px_60px_rgba(15,23,42,0.10)]">
          <div className="mx-auto grid max-w-[520px] gap-5">
            <Skeleton className="mx-auto h-8 w-32" />
            <Skeleton className="mx-auto h-4 w-72" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="mt-2 grid gap-3">
                <div className="flex items-center gap-3">
                  <Skeleton className="h-6 w-24" />
                  <Skeleton className="h-px flex-1" />
                </div>
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function WorkspaceContentSkeleton() {
  return (
    <Card className="min-h-[520px] rounded-3xl border-border/80">
      <CardContent className="space-y-6 p-6">
        <div className="flex items-center justify-between gap-4">
          <div className="grid gap-2">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-3 w-64" />
          </div>
          <Skeleton className="h-10 w-28 rounded-2xl" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-56 rounded-3xl" />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function GalleryCardSkeleton({ isCreate = false }: { isCreate?: boolean }) {
  return (
    <Card className="h-full rounded-(--radius-card) border-border/80 bg-card text-card-foreground shadow-none">
      <CardContent className="flex h-full flex-col p-2.5">
        <div className="rounded-[18px] bg-muted/55 p-2">
          {isCreate ? (
            <div className="flex h-[258px] items-center justify-center rounded-[14px] border border-dashed border-border bg-background">
              <Skeleton className="size-12 rounded-xl bg-primary/90" />
            </div>
          ) : (
            <div className="relative mx-auto h-[258px] w-[182px] overflow-hidden rounded-[14px] border border-zinc-200 bg-white p-5">
              <div className="grid gap-3">
                <Skeleton className="mx-auto h-4 w-12 bg-zinc-200" />
                <div className="space-y-1.5">
                  <Skeleton className="mx-auto h-2 w-24 bg-zinc-200" />
                  <Skeleton className="mx-auto h-2 w-28 bg-zinc-200" />
                </div>
                <div className="pt-2">
                  <div className="mb-2 flex items-center gap-2">
                    <Skeleton className="h-3 w-8 bg-zinc-200" />
                    <Skeleton className="h-px flex-1 bg-zinc-200" />
                  </div>
                  <div className="space-y-1.5">
                    <Skeleton className="h-2 w-16 bg-zinc-200" />
                    <Skeleton className="h-2 w-full bg-zinc-200" />
                    <Skeleton className="h-2 w-4/5 bg-zinc-200" />
                  </div>
                </div>
                <div className="pt-1">
                  <div className="mb-2 flex items-center gap-2">
                    <Skeleton className="h-3 w-10 bg-zinc-200" />
                    <Skeleton className="h-px flex-1 bg-zinc-200" />
                  </div>
                  <div className="space-y-1.5">
                    <Skeleton className="h-2 w-20 bg-zinc-200" />
                    <Skeleton className="h-2 w-full bg-zinc-200" />
                    <Skeleton className="h-2 w-3/4 bg-zinc-200" />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="flex min-h-[92px] flex-1 flex-col justify-between px-1 pt-3">
          <div className="grid gap-2">
            <Skeleton className="h-[18px] w-28" />
            <Skeleton className="h-3 w-40" />
            {isCreate ? <Skeleton className="h-3 w-32" /> : null}
          </div>

          {isCreate ? (
            <div className="grid grid-cols-2 gap-2 pt-2.5">
              <Skeleton className="h-8.5 rounded-md bg-primary/90" />
              <Skeleton className="h-8.5 rounded-md bg-background" />
            </div>
          ) : (
            <div className="mt-2 flex items-center gap-1.5">
              <Skeleton className="size-3 rounded-full" />
              <Skeleton className="h-3 w-20" />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function GalleryWorkspaceSkeleton({
  itemCount,
  includeCreateCard = false,
}: {
  itemCount: number;
  includeCreateCard?: boolean;
}) {
  const visibleItemCount = Math.max(1, itemCount);

  return (
    <section className="rounded-(--radius-workspace) border border-border bg-muted/35 p-3.5 text-foreground sm:p-4">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Skeleton className="h-9 w-full rounded-md bg-card sm:w-80 lg:w-96" />
        <div className="ml-auto flex w-full justify-end sm:w-auto">
          <Skeleton className="h-9 w-16 rounded-md bg-background" />
        </div>
      </div>

      <div className="grid auto-rows-fr grid-cols-[repeat(auto-fit,minmax(208px,228px))] gap-4">
        {includeCreateCard ? <GalleryCardSkeleton isCreate /> : null}
        {Array.from({ length: visibleItemCount }).map((_, index) => (
          <GalleryCardSkeleton key={index} />
        ))}
      </div>

      {visibleItemCount > 1 ? (
        <div className="mt-4 flex items-center justify-center gap-2">
          <Skeleton className="size-8 rounded-lg bg-background" />
          <Skeleton className="h-8 w-16 rounded-lg bg-background" />
          <Skeleton className="size-8 rounded-lg bg-background" />
        </div>
      ) : null}
    </section>
  );
}

function GalleryRouteSkeleton({
  itemCount,
  includeCreateCard = false,
}: {
  itemCount: number;
  includeCreateCard?: boolean;
}) {
  return (
    <main className="flex-1 p-4">
      <GalleryWorkspaceSkeleton
        itemCount={itemCount}
        includeCreateCard={includeCreateCard}
      />
    </main>
  );
}

function WorkspaceRouteSkeleton() {
  return (
    <main className="flex-1 p-4">
      <WorkspaceContentSkeleton />
    </main>
  );
}

function createEditorCollapsedState(resume: ResumeData, openId?: string) {
  return resume.sections.reduce(
    (state, section) => {
      state[section.id] = section.id !== openId;
      return state;
    },
    { basic: openId !== "basic" } as Record<string, boolean>,
  );
}

function collapseAllExcept(
  current: Record<string, boolean>,
  openId: string,
) {
  return Object.keys({ ...current, [openId]: false }).reduce(
    (state, key) => {
      state[key] = key !== openId;
      return state;
    },
    {} as Record<string, boolean>,
  );
}

const fontLabels: Record<
  ResumeFontFamily,
  "fontInter" | "fontSerif" | "fontPlex"
> = {
  inter: "fontInter",
  serif: "fontSerif",
  plex: "fontPlex",
};

type WorkspaceRoute =
  | { kind: "resume-gallery" }
  | { kind: "resume-detail"; id: string }
  | { kind: "template-gallery" }
  | { kind: "template-detail"; id: string }
  | { kind: "trash" }
  | { kind: "models" }
  | { kind: "settings" }
  | { kind: "unknown" };

interface PendingWorkspaceLeaveAction {
  run: () => void;
}

function getWorkspaceRoute(pathname: string): WorkspaceRoute {
  const resumeDetailMatch = matchPath("/resume/:id", pathname);

  if (resumeDetailMatch?.params.id) {
    return { kind: "resume-detail", id: resumeDetailMatch.params.id };
  }

  const templateDetailMatch = matchPath("/template/:id", pathname);

  if (templateDetailMatch?.params.id) {
    return { kind: "template-detail", id: templateDetailMatch.params.id };
  }

  if (
    matchPath({ path: "/resume", end: true }, pathname) ||
    matchPath({ path: "/dashboard", end: true }, pathname)
  ) {
    return { kind: "resume-gallery" };
  }

  if (matchPath("/templates", pathname)) {
    return { kind: "template-gallery" };
  }

  if (matchPath("/trash", pathname)) {
    return { kind: "trash" };
  }

  if (matchPath("/models", pathname)) {
    return { kind: "models" };
  }

  if (matchPath("/settings", pathname)) {
    return { kind: "settings" };
  }

  return { kind: "unknown" };
}

function getWorkspaceViewFromRoute(route: WorkspaceRoute): WorkspaceView {
  switch (route.kind) {
    case "template-gallery":
    case "template-detail":
      return "templates";
    case "trash":
      return "trash";
    case "models":
      return "models";
    case "settings":
      return "settings";
    case "resume-gallery":
    case "resume-detail":
    case "unknown":
    default:
      return "resume";
  }
}

function getResumePath(resumeId: string) {
  return `/resume/${resumeId}`;
}

function getTemplatePath(templateId: string) {
  return `/template/${templateId}`;
}

const supportedFontFamilies: ResumeFontFamily[] = ["inter", "serif", "plex"];

function normalizeFontSize(value: number) {
  return resumeFontSizeOptions.reduce((closest, current) =>
    Math.abs(current - value) < Math.abs(closest - value) ? current : closest,
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isResumeData(value: unknown): value is ResumeData {
  return (
    isRecord(value) && isRecord(value.basic) && Array.isArray(value.sections)
  );
}

function createDefaultResumeTitle(t: AppMessages, index: number) {
  return t.defaultResumeTitle.replace("{index}", String(index));
}

function normalizeResumeTitle(value: unknown, fallback: string) {
  const title = typeof value === "string" ? value.trim() : "";

  return Array.from(title || fallback)
    .slice(0, MAX_RESUME_TITLE_LENGTH)
    .join("");
}

function formatResumeTitleForToolbar(value: string) {
  const characters = Array.from(value);

  if (characters.length <= 6) {
    return value;
  }

  return `${characters.slice(0, 6).join("").trimEnd()}...`;
}

function normalizeResumeTypography(value: unknown): ResumeTypographySettings {
  if (!isRecord(value)) {
    return defaultTypography;
  }

  const fontFamily = supportedFontFamilies.includes(
    value.fontFamily as ResumeFontFamily,
  )
    ? (value.fontFamily as ResumeFontFamily)
    : defaultTypography.fontFamily;
  const fontSize =
    typeof value.fontSize === "number" && Number.isFinite(value.fontSize)
      ? normalizeFontSize(value.fontSize)
      : defaultTypography.fontSize;

  return {
    fontFamily,
    fontSize,
  };
}

function normalizeResumeTemplateSettings(
  value: unknown,
): ResumeTemplateSettings | undefined {
  return isRecord(value)
    ? createTemplateSettings("minimal", value as Partial<ResumeTemplateSettings>)
    : undefined;
}

function getPreviewPageCount(element: HTMLElement | null) {
  const rawPageCount = element?.dataset.resumePageCount;
  const pageCount = rawPageCount ? Number(rawPageCount) : 1;

  return Number.isFinite(pageCount) && pageCount > 0 ? pageCount : 1;
}

function waitForPreviewPagination() {
  let remainingFrames = 8;

  // ResumePreview schedules pagination in requestAnimationFrame after layout.
  // Waiting a few frames keeps the fit check tied to the rendered preview
  // instead of duplicating the pagination algorithm here.
  return new Promise<void>((resolve) => {
    const tick = () => {
      remainingFrames -= 1;

      if (remainingFrames <= 0) {
        resolve();
        return;
      }

      window.requestAnimationFrame(tick);
    };

    window.requestAnimationFrame(tick);
  });
}

function getNextSmallerFontSize(fontSize: number) {
  const smallerSizes = resumeFontSizeOptions.filter(
    (size) => size < fontSize,
  );

  return smallerSizes.at(-1) ?? fontSize;
}

function compactNumber(current: number, target: number | undefined, min: number) {
  return Number(Math.max(min, Math.min(current, target ?? current)).toFixed(2));
}

function compactPagePadding(current: number, delta: number) {
  return Math.max(8, current - delta);
}

function createSmartOnePageSettingsCandidate(
  settings: ResumeTemplateSettings,
  level: (typeof SMART_ONE_PAGE_LAYOUT_LEVELS)[number],
): ResumeTemplateSettings {
  return {
    ...settings,
    pagePaddingTop: compactPagePadding(settings.pagePaddingTop, level.pagePaddingDelta),
    pagePaddingX: compactPagePadding(settings.pagePaddingX, level.pagePaddingDelta),
    pagePaddingBottom: compactPagePadding(
      settings.pagePaddingBottom,
      level.pagePaddingDelta,
    ),
    sectionGap: compactNumber(settings.sectionGap, level.sectionGap, 0.8),
    itemGap: compactNumber(settings.itemGap, level.itemGap, 0.4),
    bodyLineHeight: compactNumber(
      settings.bodyLineHeight,
      level.bodyLineHeight,
      1.4,
    ),
    nameScale: compactNumber(settings.nameScale, level.nameScale, 1.6),
    sectionTitleScale: compactNumber(
      settings.sectionTitleScale,
      level.sectionTitleScale,
      0.75,
    ),
    itemTitleScale: compactNumber(
      settings.itemTitleScale,
      level.itemTitleScale,
      0.85,
    ),
    metaScale: compactNumber(settings.metaScale, level.metaScale, 0.75),
    bodyScale: compactNumber(settings.bodyScale, level.bodyScale, 0.85),
  };
}

function areTemplateSettingsEqual(
  left: ResumeTemplateSettings,
  right: ResumeTemplateSettings,
) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function areSmartOnePageSnapshotsEqual(
  left: SmartOnePageStyleSnapshot,
  right: SmartOnePageStyleSnapshot,
) {
  return (
    left.typography.fontFamily === right.typography.fontFamily &&
    left.typography.fontSize === right.typography.fontSize &&
    Boolean(left.templateSettings) === Boolean(right.templateSettings) &&
    (!left.templateSettings ||
      !right.templateSettings ||
      areTemplateSettingsEqual(left.templateSettings, right.templateSettings))
  );
}

function createSmartOnePageCandidates(
  typography: ResumeTypographySettings,
  settings: ResumeTemplateSettings,
) {
  const candidates: SmartOnePageStyleSnapshot[] = [];
  let fontSize = typography.fontSize;

  SMART_ONE_PAGE_LAYOUT_LEVELS.forEach((level, index) => {
    if (index > 0) {
      fontSize = Math.max(
        SMART_ONE_PAGE_MIN_FONT_SIZE,
        getNextSmallerFontSize(fontSize),
      );
    }

    candidates.push({
      typography: {
        ...typography,
        fontSize,
      },
      templateSettings: createSmartOnePageSettingsCandidate(settings, level),
    });
  });

  const strongestLevel =
    SMART_ONE_PAGE_LAYOUT_LEVELS[SMART_ONE_PAGE_LAYOUT_LEVELS.length - 1];

  while (fontSize > SMART_ONE_PAGE_MIN_FONT_SIZE) {
    fontSize = Math.max(
      SMART_ONE_PAGE_MIN_FONT_SIZE,
      getNextSmallerFontSize(fontSize),
    );

    candidates.push({
      typography: {
        ...typography,
        fontSize,
      },
      templateSettings: createSmartOnePageSettingsCandidate(
        settings,
        strongestLevel,
      ),
    });
  }

  return candidates.filter((candidate, index, allCandidates) => {
    const firstMatchingIndex = allCandidates.findIndex((item) =>
      areSmartOnePageSnapshotsEqual(item, candidate),
    );

    return firstMatchingIndex === index;
  });
}

function normalizeResumeTemplateId(
  value: unknown,
  fallbackTemplateId: ResumeTemplateId,
) {
  return typeof value === "string" && value.trim()
    ? value
    : fallbackTemplateId;
}

function formatControlNumber(value: number, precision: number) {
  const formattedValue = value.toFixed(precision);

  return formattedValue.includes(".")
    ? formattedValue.replace(/\.?0+$/, "")
    : formattedValue;
}

function FormatSliderField({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  const precision = step < 1 ? 2 : 0;
  const [inputValue, setInputValue] = useState(() =>
    formatControlNumber(value, precision),
  );

  useEffect(() => {
    setInputValue(formatControlNumber(value, precision));
  }, [precision, value]);

  function commitInputValue(nextInputValue: string) {
    if (!nextInputValue.trim()) {
      setInputValue(formatControlNumber(value, precision));
      return;
    }

    const parsedValue = Number(nextInputValue);

    if (!Number.isFinite(parsedValue)) {
      setInputValue(formatControlNumber(value, precision));
      return;
    }

    const clampedValue = Math.min(max, Math.max(min, parsedValue));
    const steppedValue =
      Math.round((clampedValue - min) / step) * step + min;
    const nextValue = Number(
      Math.min(max, Math.max(min, steppedValue)).toFixed(precision),
    );

    setInputValue(formatControlNumber(nextValue, precision));
    onChange(nextValue);
  }

  return (
    <div className="grid gap-2 py-1">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <div className="flex items-center gap-0.5">
          <Input
            aria-label={label}
            inputMode="decimal"
            value={inputValue}
            className="h-7 w-9 rounded-md border-0 bg-muted/60 px-1.5 py-0 text-center text-sm tabular-nums text-muted-foreground shadow-none focus-visible:border-transparent focus-visible:ring-1"
            onBlur={(event) => commitInputValue(event.currentTarget.value)}
            onChange={(event) => {
              const nextValue = event.currentTarget.value;

              if (/^\d*\.?\d*$/.test(nextValue)) {
                setInputValue(nextValue);
              }
            }}
            onFocus={(event) => event.currentTarget.select()}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitInputValue(event.currentTarget.value);
                event.currentTarget.blur();
              }

              if (event.key === "Escape") {
                event.preventDefault();
                setInputValue(formatControlNumber(value, precision));
                event.currentTarget.blur();
              }
            }}
          />
          {suffix ? (
            <span className="text-sm tabular-nums text-muted-foreground">
              {suffix}
            </span>
          ) : null}
        </div>
      </div>
      <Slider
        className="[&_[data-slot=slider-thumb]]:size-3.5 [&_[data-slot=slider-track]]:h-1.5 [&_[data-slot=slider-track]]:bg-muted/70"
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={([nextValue]) => {
          if (typeof nextValue === "number") {
            onChange(nextValue);
          }
        }}
      />
    </div>
  );
}

function normalizeStoredResumeDocument(
  value: unknown,
  locale: Locale,
  fallbackTemplateId: ResumeTemplateId,
  index: number,
): ResumeWorkspaceItem | null {
  if (!isRecord(value) || !isResumeData(value.resume)) {
    return null;
  }

  const fallbackTitle =
    value.resume.basic.name || createDefaultResumeTitle(getMessagesSync(locale), index);
  const id = typeof value.id === "string" ? value.id.trim() : "";

  if (!id) {
    return null;
  }

  return {
    id,
    title: normalizeResumeTitle(value.title, fallbackTitle),
    updatedAt:
      typeof value.updatedAt === "string" && value.updatedAt.trim()
        ? value.updatedAt
        : new Date().toISOString(),
    resume: normalizeResumeContactFields(value.resume),
    jobBrief: typeof value.jobBrief === "string" ? value.jobBrief : "",
    typography: normalizeResumeTypography(value.typography),
    template: normalizeResumeTemplateId(value.template, fallbackTemplateId),
    templateSettings: normalizeResumeTemplateSettings(value.templateSettings),
  };
}

function normalizeResumeContactFields(resume: ResumeData): ResumeData {
  // Legacy resume JSON has no contact type. Keep those fields as plain text
  // instead of guessing from labels such as "GitHub" or "Portfolio".
  return {
    ...resume,
    basic: {
      ...resume.basic,
      customFields: resume.basic.customFields.map((field) => ({
        ...field,
        type: normalizeContactFieldType(field.type),
      })),
    },
  };
}

function normalizeResumeDocuments(
  source: unknown,
  locale: Locale,
  fallbackTemplateId: ResumeTemplateId = defaultTemplate,
) {
  if (
    source &&
    typeof source === "object" &&
    "resumes" in source &&
    Array.isArray((source as { resumes?: unknown[] }).resumes) &&
    (source as { resumes: unknown[] }).resumes.length > 0
  ) {
    const normalized = (source as { resumes: unknown[] }).resumes
      .map((item, index) =>
        normalizeStoredResumeDocument(
          item,
          locale,
          fallbackTemplateId,
          index + 1,
        ),
      )
      .filter((item): item is ResumeWorkspaceItem => Boolean(item));

    return normalized;
  }

  if (
    source &&
    typeof source === "object" &&
    "resume" in source &&
    (source as { resume?: ResumeData }).resume
  ) {
    return [];
  }

  return [];
}

function normalizeImportedResumeDocuments(
  source: unknown,
  fallbackTemplateId: ResumeTemplateId = defaultTemplate,
) {
  const importedAt = new Date().toISOString();

  function normalizeItem(value: unknown): ResumeWorkspaceItem | null {
    if (isResumeData(value)) {
      return null;
    }

    if (!isRecord(value)) {
      return null;
    }

    const rawResume = isResumeData(value.resume) ? value.resume : null;

    if (!rawResume) {
      return null;
    }

    const id = typeof value.id === "string" ? value.id.trim() : "";

    if (!id) {
      return null;
    }

    const typography = normalizeResumeTypography(value.typography);
    const template = normalizeResumeTemplateId(value.template, fallbackTemplateId);

    return {
      id,
      title: normalizeResumeTitle(
        value.title,
        rawResume.basic.name || "Resume",
      ),
      updatedAt:
        typeof value.updatedAt === "string" ? value.updatedAt : importedAt,
      resume: normalizeResumeContactFields(rawResume),
      jobBrief: typeof value.jobBrief === "string" ? value.jobBrief : "",
      typography,
      template,
      templateSettings: normalizeResumeTemplateSettings(value.templateSettings),
    };
  }

  if (Array.isArray(source)) {
    return source
      .map(normalizeItem)
      .filter((item): item is ResumeWorkspaceItem => Boolean(item));
  }

  if (isRecord(source) && Array.isArray(source.resumes)) {
    return source.resumes
      .map(normalizeItem)
      .filter((item): item is ResumeWorkspaceItem => Boolean(item));
  }

  const single = normalizeItem(source);
  return single ? [single] : [];
}

function normalizeDeletedResumeDocuments(
  source: unknown,
  fallbackTemplateId: ResumeTemplateId = defaultTemplate,
): DeletedResumeWorkspaceItem[] {
  if (
    !source ||
    typeof source !== "object" ||
    !("deletedResumes" in source) ||
    !Array.isArray((source as { deletedResumes?: unknown[] }).deletedResumes)
  ) {
    return [];
  }

  const normalizedItems: DeletedResumeWorkspaceItem[] = [];

  for (const item of (source as { deletedResumes: unknown[] }).deletedResumes) {
    if (!isRecord(item) || !("resume" in item)) {
      continue;
    }

    const normalized = normalizeImportedResumeDocuments(
      item,
      fallbackTemplateId,
    )[0];

    if (!normalized) {
      continue;
    }

    normalizedItems.push({
      ...normalized,
      deletedAt:
        typeof item.deletedAt === "string" && item.deletedAt.trim()
          ? item.deletedAt
          : new Date().toISOString(),
      updatedAt:
        typeof item.updatedAt === "string" && item.updatedAt.trim()
          ? item.updatedAt
          : normalized.updatedAt,
      template:
        typeof item.template === "string" && item.template.trim()
          ? item.template
          : normalized.template,
    });
  }

  return normalizedItems;
}

function stripWorkspaceVolatileFields(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stripWorkspaceVolatileFields);
  }

  if (!isRecord(value)) {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => key !== "savedAt" && key !== "updatedAt")
      .filter(([key]) => key !== "agentSettings" && key !== "theme")
      .filter(([, entryValue]) => typeof entryValue !== "undefined")
      .map(([key, entryValue]) => [
        key,
        stripWorkspaceVolatileFields(entryValue),
      ]),
  );
}

function createResumeFingerprint(item: ResumeWorkspaceItem | null) {
  return item ? JSON.stringify(stripWorkspaceVolatileFields(item)) : "";
}

function countValueChanges(before: unknown, after: unknown): number {
  if (Object.is(before, after)) {
    return 0;
  }

  if (Array.isArray(before) && Array.isArray(after)) {
    const sharedLength = Math.min(before.length, after.length);
    let changeCount = Math.abs(before.length - after.length);

    for (let index = 0; index < sharedLength; index += 1) {
      changeCount += countValueChanges(before[index], after[index]);
    }

    return changeCount;
  }

  if (isRecord(before) && isRecord(after)) {
    const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
    let changeCount = 0;

    keys.forEach((key) => {
      if (!(key in before) || !(key in after)) {
        changeCount += 1;
        return;
      }

      changeCount += countValueChanges(before[key], after[key]);
    });

    return changeCount;
  }

  return 1;
}

function countResumeChanges(
  before: ResumeWorkspaceItem | null,
  after: ResumeWorkspaceItem | null,
) {
  return countValueChanges(
    stripWorkspaceVolatileFields(before),
    stripWorkspaceVolatileFields(after),
  );
}

function countTemplateChanges(
  before: ResumeTemplateDefinition | null,
  after: ResumeTemplateDefinition | null,
) {
  return countValueChanges(
    stripWorkspaceVolatileFields(before),
    stripWorkspaceVolatileFields(after),
  );
}

function createTemplateFingerprint(item: ResumeTemplateDefinition | null) {
  return item ? JSON.stringify(stripWorkspaceVolatileFields(item)) : "";
}

function normalizeWorkspaceTheme(value: unknown): ThemeMode {
  return value === "dark" || value === "system" ? value : "light";
}

interface UserSettingsSnapshot {
  locale: Locale;
  theme: ThemeMode;
  agentSettings: AgentSettings;
}

export function ResumeBuilder({
  locale,
  messages,
  onLocaleChange,
  onLogout,
}: {
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
}) {
  const t = messages;
  const navigate = useNavigate();
  const location = useLocation();
  const initialLocaleRef = useRef(locale);

  const [theme, setTheme] = useState<ThemeMode>("light");
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">("light");
  // Initialize from the URL so direct visits never paint the resume shell first.
  const [activeView, setActiveView] = useState<WorkspaceView>(() =>
    getWorkspaceViewFromRoute(getWorkspaceRoute(location.pathname)),
  );
  const [resumeDocuments, setResumeDocuments] = useState<ResumeWorkspaceItem[]>(
    [],
  );
  const [deletedResumeDocuments, setDeletedResumeDocuments] = useState<
    DeletedResumeWorkspaceItem[]
  >([]);
  const [activeResumeId, setActiveResumeId] = useState<string | null>(null);
  const [showResumeGallery, setShowResumeGallery] = useState(true);
  const [showTemplateGallery, setShowTemplateGallery] = useState(true);
  const [resume, setResume] = useState<ResumeData>(() => createEmptyResume());
  const [collapsedState, setCollapsedState] = useState<Record<string, boolean>>(
    createEditorCollapsedState(createEmptyResume()),
  );
  const [jobBrief, setJobBrief] = useState("");
  const [typography, setTypography] =
    useState<ResumeTypographySettings>(defaultTypography);
  const [template, setTemplate] = useState<ResumeTemplateId>(defaultTemplate);
  const [templateSettings, setTemplateSettings] =
    useState<ResumeTemplateSettings | null>(null);
  const [defaultTemplateId, setDefaultTemplateId] =
    useState<ResumeTemplateId>(defaultTemplate);
  const [customTemplates, setCustomTemplates] = useState<
    ResumeTemplateDefinition[]
  >([]);
  const [deletedTemplates, setDeletedTemplates] = useState<
    DeletedResumeTemplateDefinition[]
  >([]);
  const [modelConfigs, setModelConfigs] = useState<ModelConfig[]>([]);
  const [agentSettings, setAgentSettings] = useState<AgentSettings>(
    createDefaultAgentSettings(),
  );
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isCreatingResume, setIsCreatingResume] = useState(false);
  const [isDuplicatingResume, setIsDuplicatingResume] = useState(false);
  const [isCreatingTemplate, setIsCreatingTemplate] = useState(false);
  const [settingDefaultTemplateId, setSettingDefaultTemplateId] = useState<
    string | null
  >(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">(
    "idle",
  );
  const [isResumeTitleDialogOpen, setIsResumeTitleDialogOpen] =
    useState(false);
  const [pendingWorkspaceLeaveAction, setPendingWorkspaceLeaveAction] =
    useState<PendingWorkspaceLeaveAction | null>(null);
  const [isResolvingWorkspaceLeave, setIsResolvingWorkspaceLeave] =
    useState(false);
  const [resumeTitleDraft, setResumeTitleDraft] = useState("");
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);
  const [workspaceVersions, setWorkspaceVersions] = useState<
    WorkspaceVersionSummary[]
  >([]);
  const [activeWorkspaceVersionId, setActiveWorkspaceVersionId] = useState<
    string | null
  >(null);
  const [avatarCropSource, setAvatarCropSource] = useState<string | null>(null);
  const [isAgentPanelCollapsed, setIsAgentPanelCollapsed] = useState(false);
  const [isAgentSheetOpen, setIsAgentSheetOpen] = useState(false);
  const [isAgentDockLayout, setIsAgentDockLayout] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia(AGENT_DOCK_MEDIA_QUERY).matches
      : false,
  );
  const [agentDraft, setAgentDraft] = useState<AgentDraftState | null>(null);
  const [lastAgentDraft, setLastAgentDraft] = useState<AgentDraftState | null>(
    null,
  );
  const [previewScale, setPreviewScale] = useState(1);
  const [previewPageHeight, setPreviewPageHeight] = useState(A4_HEIGHT_PX);
  const [isSmartFittingOnePage, setIsSmartFittingOnePage] = useState(false);
  const [documentStickyTop, setDocumentStickyTop] = useState(96);
  const documentHeaderRef = useRef<HTMLElement | null>(null);
  const previewScaleFrameRef = useRef<HTMLDivElement | null>(null);
  const previewRef = useRef<HTMLElement | null>(null);
  const exportInFlightRef = useRef(false);
  const importInFlightRef = useRef(false);
  // Refs close the same-render double-click gap before disabled states commit.
  const createResumeInFlightRef = useRef(false);
  const duplicateResumeInFlightRef = useRef(false);
  const createTemplateInFlightRef = useRef(false);
  const setDefaultTemplateInFlightRef = useRef(false);
  const userSettingsSaveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const userSettingsMutationIdRef = useRef(0);
  const persistedUserSettingsRef = useRef<UserSettingsSnapshot>({
    locale: initialLocaleRef.current,
    theme: "light",
    agentSettings: createDefaultAgentSettings(),
  });
  const saveRequestRef = useRef<Promise<SaveResponse> | null>(null);
  const pendingSaveAfterCurrentRef = useRef(false);
  const versionLoadRequestRef = useRef<string | null>(null);
  const resumeDetailRequestRef = useRef<string | null>(null);
  const lastLoadedResumeDetailIdRef = useRef<string | null>(null);
  const lastPersistedResumeRef = useRef<string | null>(null);
  const lastPersistedResumeItemRef = useRef<ResumeWorkspaceItem | null>(null);
  const recentlySavedResumeFingerprintsRef = useRef<Set<string>>(new Set());
  const lastPersistedTemplateRef = useRef<string | null>(null);
  const lastPersistedTemplateItemRef =
    useRef<ResumeTemplateDefinition | null>(null);
  const lastOpenedTemplateIdRef = useRef<string | null>(null);
  const defaultTemplateIdRef = useRef<ResumeTemplateId>(defaultTemplate);
  const currentResumeRef = useRef(resume);
  const agentDraftBaseRef = useRef<{
    draftId: string;
    resume: ResumeData;
  } | null>(null);
  currentResumeRef.current = resume;

  const effectiveResume = agentDraft?.resume ?? resume;
  const agentDraftState = agentDraft ?? lastAgentDraft;
  const previewResume = useDeferredValue(effectiveResume);
  const templatePreviewResume = useMemo(
    () => createTemplatePreviewResume(t),
    [t],
  );
  const deferredTemplatePreviewResume = useDeferredValue(templatePreviewResume);
  const deferredJobBrief = useDeferredValue(jobBrief);
  const deletedTemplateIds = useMemo(
    () => deletedTemplates.map((item) => item.id),
    [deletedTemplates],
  );
  const templateCatalog = useMemo(
    () => getTemplateCatalog(t, customTemplates, deletedTemplateIds),
    [customTemplates, deletedTemplateIds, t],
  );
  const activeTemplateDefinition = getTemplateById(
    templateCatalog,
    template,
    defaultTemplateId,
  );
  const activeResumeTemplateDefinition = useMemo<ResumeTemplateDefinition>(
    () =>
      templateSettings
        ? {
            ...activeTemplateDefinition,
            settings: templateSettings,
          }
        : activeTemplateDefinition,
    [activeTemplateDefinition, templateSettings],
  );
  const previewDocument =
    activeView === "templates" ? deferredTemplatePreviewResume : previewResume;
  const currentRoute = useMemo(
    () => getWorkspaceRoute(location.pathname),
    [location.pathname],
  );

  useEffect(() => {
    defaultTemplateIdRef.current = defaultTemplateId;
  }, [defaultTemplateId]);

  const keywordMatch = useMemo(
    () => getKeywordMatch(previewResume, deferredJobBrief, 0, t),
    [deferredJobBrief, previewResume, t],
  );
  const pageEyebrow =
    activeView === "resume"
      ? t.myResume
      : activeView === "templates"
        ? t.resumeTemplates
        : activeView === "trash"
          ? t.recycleBin
          : activeView === "models"
            ? t.modelSettings
            : t.settings;
  const isResumeDetailView = activeView === "resume" && !showResumeGallery;
  const isTemplateDetailView =
    activeView === "templates" && !showTemplateGallery;
  const activeResumeDocument = useMemo(
    () => resumeDocuments.find((item) => item.id === activeResumeId) ?? null,
    [activeResumeId, resumeDocuments],
  );
  const activeResumeTitle = activeResumeDocument?.title ?? "";
  const activeResumeToolbarTitle = activeResumeTitle || t.untitledResume;
  const resumeTitleSaveLabel = t.saveResumeTitle;
  const showEditorControls =
    activeView !== "trash" &&
    activeView !== "models" &&
    activeView !== "settings" &&
    !(
      (activeView === "resume" && showResumeGallery) ||
      (activeView === "templates" && showTemplateGallery)
    );
  const canSaveCurrentWorkspace =
    isResumeDetailView ||
    (isTemplateDetailView && !activeTemplateDefinition.isBuiltIn);

  useEffect(() => {
    const mediaQuery = window.matchMedia(AGENT_DOCK_MEDIA_QUERY);
    const syncAgentLayout = () => {
      setIsAgentDockLayout(mediaQuery.matches);
      if (mediaQuery.matches) {
        setIsAgentSheetOpen(false);
      }
    };

    syncAgentLayout();
    mediaQuery.addEventListener("change", syncAgentLayout);
    return () => mediaQuery.removeEventListener("change", syncAgentLayout);
  }, []);

  useEffect(() => {
    if (!isResumeDetailView) {
      setIsAgentSheetOpen(false);
    }
  }, [isResumeDetailView]);

  useEffect(() => {
    if (!isResumeDetailView && !isTemplateDetailView) {
      setDocumentStickyTop(96);
      return;
    }

    const headerElement = documentHeaderRef.current;

    if (!headerElement) {
      return;
    }

    const syncDocumentStickyTop = () => {
      const nextStickyTop = Math.ceil(
        headerElement.getBoundingClientRect().height + 16,
      );

      setDocumentStickyTop((current) =>
        current === nextStickyTop ? current : nextStickyTop,
      );
    };

    syncDocumentStickyTop();

    const resizeObserver = new ResizeObserver(syncDocumentStickyTop);
    resizeObserver.observe(headerElement);
    window.addEventListener("resize", syncDocumentStickyTop);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener("resize", syncDocumentStickyTop);
    };
  }, [isResumeDetailView, isTemplateDetailView]);

  useEffect(() => {
    if (!isResumeDetailView && !isTemplateDetailView) {
      setPreviewScale(1);
      setPreviewPageHeight(A4_HEIGHT_PX);
      return;
    }

    const frameElement = previewScaleFrameRef.current;

    if (!frameElement) {
      return;
    }

    let animationFrameId = 0;

    const syncPreviewScale = () => {
      const frameWidth = frameElement.clientWidth || A4_WIDTH_PX;
      const availableWidth = Math.max(
        frameWidth - PREVIEW_FRAME_GUTTER_PX,
        frameWidth * 0.88,
      );
      const nextScale = Math.min(1, availableWidth / A4_WIDTH_PX);
      const pageHeight = previewRef.current?.offsetHeight || A4_HEIGHT_PX;

      setPreviewScale(nextScale);
      setPreviewPageHeight(pageHeight);
    };

    const syncPreviewScaleDuringLayoutTransition = () => {
      window.cancelAnimationFrame(animationFrameId);

      let remainingFrames = 24;
      const tick = () => {
        syncPreviewScale();
        remainingFrames -= 1;

        if (remainingFrames > 0) {
          animationFrameId = window.requestAnimationFrame(tick);
        }
      };

      animationFrameId = window.requestAnimationFrame(tick);
    };

    syncPreviewScale();
    syncPreviewScaleDuringLayoutTransition();

    const resizeObserver = new ResizeObserver(
      syncPreviewScaleDuringLayoutTransition,
    );
    resizeObserver.observe(frameElement);

    if (previewRef.current) {
      resizeObserver.observe(previewRef.current);
    }

    window.addEventListener("resize", syncPreviewScaleDuringLayoutTransition);

    return () => {
      window.cancelAnimationFrame(animationFrameId);
      resizeObserver.disconnect();
      window.removeEventListener(
        "resize",
        syncPreviewScaleDuringLayoutTransition,
      );
    };
  }, [
    isAgentPanelCollapsed,
    isResumeDetailView,
    isTemplateDetailView,
  ]);

  useEffect(() => {
    const root = document.documentElement;
    const mediaQuery = window.matchMedia?.("(prefers-color-scheme: dark)");

    function applyTheme() {
      const nextTheme =
        theme === "system"
          ? mediaQuery?.matches
            ? "dark"
            : "light"
          : theme;

      root.classList.toggle("dark", nextTheme === "dark");
      root.style.colorScheme = nextTheme;
      setResolvedTheme(nextTheme);
    }

    applyTheme();

    if (theme !== "system" || !mediaQuery) {
      return;
    }

    mediaQuery.addEventListener("change", applyTheme);

    return () => {
      mediaQuery.removeEventListener("change", applyTheme);
    };
  }, [theme]);

  useEffect(() => {
    if (isLoading || !activeResumeId) {
      return;
    }

    setResumeDocuments((current) =>
      current.map((item) => {
        if (item.id !== activeResumeId) {
          return item;
        }

        const nextTypography = typography;
        const nextTemplate = template;
        const nextTemplateSettings = templateSettings ?? undefined;

        if (
          item.resume === resume &&
          item.jobBrief === jobBrief &&
          item.template === nextTemplate &&
          item.templateSettings === nextTemplateSettings &&
          item.typography?.fontFamily === nextTypography.fontFamily &&
          item.typography?.fontSize === nextTypography.fontSize
        ) {
          return item;
        }

        return {
          ...item,
          updatedAt: new Date().toISOString(),
          resume,
          jobBrief,
          template: nextTemplate,
          templateSettings: nextTemplateSettings,
          typography: nextTypography,
        };
      }),
    );
  }, [
    activeResumeId,
    isLoading,
    jobBrief,
    resume,
    template,
    templateSettings,
    typography,
  ]);

  const buildActiveResumeItem = useCallback(
    (updatedAt: string): ResumeWorkspaceItem | null => {
      if (!activeResumeId || !activeResumeDocument) {
        return null;
      }

      return {
        ...activeResumeDocument,
        resume,
        jobBrief,
        template,
        templateSettings: templateSettings ?? undefined,
        typography,
        updatedAt,
      };
    },
    [
      activeResumeDocument,
      activeResumeId,
      jobBrief,
      resume,
      template,
      templateSettings,
      typography,
    ],
  );

  const unsavedWorkspaceChangeCount = useMemo(() => {
    if (isResumeDetailView) {
      return countResumeChanges(
        lastPersistedResumeItemRef.current,
        buildActiveResumeItem(lastSavedAt ?? ""),
      );
    }

    if (!isTemplateDetailView || activeTemplateDefinition.isBuiltIn) {
      return 0;
    }

    return countTemplateChanges(
      lastPersistedTemplateItemRef.current,
      activeTemplateDefinition,
    );
  }, [
    activeTemplateDefinition,
    buildActiveResumeItem,
    isResumeDetailView,
    isTemplateDetailView,
    lastSavedAt,
  ]);

  const saveCurrentWorkspace = useCallback(async () => {
    if (saveRequestRef.current) {
      pendingSaveAfterCurrentRef.current = true;
      return saveRequestRef.current;
    }

    const isEditingCustomTemplate =
      activeView === "templates" &&
      !showTemplateGallery &&
      !activeTemplateDefinition.isBuiltIn;
    const stableActiveResume = buildActiveResumeItem(lastSavedAt ?? "");
    const stableResumeFingerprint = createResumeFingerprint(stableActiveResume);
    const stableTemplateFingerprint = isEditingCustomTemplate
      ? createTemplateFingerprint(activeTemplateDefinition)
      : null;
    if (
      (isEditingCustomTemplate
        ? stableTemplateFingerprint === lastPersistedTemplateRef.current
        : stableResumeFingerprint === lastPersistedResumeRef.current) &&
      lastSavedAt &&
      (isEditingCustomTemplate || activeWorkspaceVersionId || !stableActiveResume)
    ) {
      setSaveState("saved");
      return {
        savedAt: lastSavedAt,
        versionId: activeWorkspaceVersionId ?? undefined,
      } satisfies SaveResponse;
    }

    const savedAt = new Date().toISOString();
    const request = (async () => {
      setSaveState("saving");
      recentlySavedResumeFingerprintsRef.current.clear();

      try {
        const nextActiveResume = buildActiveResumeItem(savedAt);
        let result: SaveResponse = {
          savedAt: lastSavedAt ?? savedAt,
          versionId: activeWorkspaceVersionId ?? undefined,
        };

        if (isEditingCustomTemplate) {
          const savedTemplate = await saveTemplateApi(
            activeTemplateDefinition.id,
            activeTemplateDefinition,
          );

          result = {
            savedAt: savedTemplate.template.updatedAt || savedAt,
          };
          lastPersistedTemplateRef.current = createTemplateFingerprint(
            savedTemplate.template,
          );
          lastPersistedTemplateItemRef.current = savedTemplate.template;
          lastOpenedTemplateIdRef.current = savedTemplate.template.id;
          setCustomTemplates((current) =>
            current.map((item) =>
              item.id === savedTemplate.template.id
                ? savedTemplate.template
                : item,
            ),
          );
          setTemplate(savedTemplate.template.id);
          setLastSavedAt(result.savedAt);
        } else if (
          nextActiveResume &&
          createResumeFingerprint(nextActiveResume) !==
            lastPersistedResumeRef.current
        ) {
          const submittedResumeFingerprint =
            createResumeFingerprint(nextActiveResume);
          const savedResume = await saveResumeApi(nextActiveResume.id, {
            title: nextActiveResume.title,
            resume: nextActiveResume.resume,
            jobBrief: nextActiveResume.jobBrief,
            typography: nextActiveResume.typography,
            template: nextActiveResume.template,
            templateSettings: templateSettings ?? null,
          });

          result = {
            savedAt: savedResume.savedAt,
            versionId: savedResume.versionId,
          };
          const savedResumeFingerprint = createResumeFingerprint(
            savedResume.resume,
          );
          lastPersistedResumeRef.current = savedResumeFingerprint;
          recentlySavedResumeFingerprintsRef.current = new Set(
            [submittedResumeFingerprint, savedResumeFingerprint].filter(Boolean),
          );
          lastPersistedResumeItemRef.current = savedResume.resume;
          lastLoadedResumeDetailIdRef.current = savedResume.resume.id;
          setResumeDocuments((current) =>
            current.map((item) =>
              item.id === savedResume.resume.id ? savedResume.resume : item,
            ),
          );
          setLastSavedAt(savedResume.savedAt);
          setActiveWorkspaceVersionId(savedResume.versionId);

          try {
            const versions = await fetchResumeVersionsApi(savedResume.resume.id);
            setWorkspaceVersions(versions.versions);
          } catch (versionsError) {
            console.error("Failed to refresh resume versions.", versionsError);
          }
        }

        setHasLoadError(false);
        setSaveState("saved");

        return result;
      } catch (error) {
        setHasLoadError(true);
        setSaveState("idle");
        throw error;
      }
    })();

    saveRequestRef.current = request;

    try {
      return await request;
    } catch (error) {
      pendingSaveAfterCurrentRef.current = false;
      setSaveState("idle");
      throw error;
    } finally {
      saveRequestRef.current = null;
    }
  }, [
    activeWorkspaceVersionId,
    activeTemplateDefinition,
    activeView,
    buildActiveResumeItem,
    lastSavedAt,
    showTemplateGallery,
    templateSettings,
  ]);

  useEffect(() => {
    if (
      saveState !== "saved" ||
      !pendingSaveAfterCurrentRef.current ||
      isLoading
    ) {
      return;
    }

    pendingSaveAfterCurrentRef.current = false;
    void saveCurrentWorkspace();
  }, [
    isLoading,
    saveCurrentWorkspace,
    saveState,
  ]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "s") {
        return;
      }

      event.preventDefault();

      if (isLoading || saveState === "saving" || !canSaveCurrentWorkspace) {
        return;
      }

      void saveCurrentWorkspace();
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [canSaveCurrentWorkspace, isLoading, saveCurrentWorkspace, saveState]);

  useEffect(() => {
    if (isLoading || saveState === "saving") {
      return;
    }

    const isEditingCustomTemplate =
      activeView === "templates" &&
      !showTemplateGallery &&
      !activeTemplateDefinition.isBuiltIn;
    const activeFingerprint = isEditingCustomTemplate
      ? createTemplateFingerprint(activeTemplateDefinition)
      : createResumeFingerprint(buildActiveResumeItem(lastSavedAt ?? ""));
    const persistedFingerprint = isEditingCustomTemplate
      ? lastPersistedTemplateRef.current
      : lastPersistedResumeRef.current;

    if (activeFingerprint === persistedFingerprint) {
      return;
    }

    // A successful save can briefly render either the submitted editor payload
    // or the backend-normalized payload before React finishes syncing state.
    if (
      !isEditingCustomTemplate &&
      saveState === "saved" &&
      recentlySavedResumeFingerprintsRef.current.has(activeFingerprint)
    ) {
      return;
    }

    setSaveState("idle");
  }, [
    activeTemplateDefinition,
    activeView,
    buildActiveResumeItem,
    isLoading,
    lastSavedAt,
    saveState,
    showTemplateGallery,
  ]);

  useEffect(() => {
    if (saveState !== "saved") {
      return;
    }

    const timer = window.setTimeout(() => {
      setSaveState("idle");
    }, 1800);

    return () => {
      window.clearTimeout(timer);
    };
  }, [saveState]);

  const hydrateResumeWorkspace = useCallback((item: ResumeWorkspaceItem) => {
    agentDraftBaseRef.current = null;
    setAgentDraft(null);
    setLastAgentDraft(null);
    setResume(item.resume);
    setCollapsedState(createEditorCollapsedState(item.resume));
    setJobBrief(item.jobBrief);
    setTypography(item.typography ?? defaultTypography);
    setTemplate(item.template ?? defaultTemplateIdRef.current);
    setTemplateSettings(item.templateSettings ?? null);
  }, []);

  const resetResumeWorkspace = useCallback(() => {
    const emptyResume = createEmptyResume();

    agentDraftBaseRef.current = null;
    setAgentDraft(null);
    setLastAgentDraft(null);
    setResume(emptyResume);
    setCollapsedState(createEditorCollapsedState(emptyResume));
    setJobBrief("");
    setTypography(defaultTypography);
    setTemplate(defaultTemplateIdRef.current);
    setTemplateSettings(null);
  }, []);

  const hasUnsavedCurrentWorkspaceChanges = useCallback(() => {
    if (saveState === "saving") {
      return false;
    }

    if (isResumeDetailView) {
      const stableActiveResume = buildActiveResumeItem(lastSavedAt ?? "");

      return Boolean(
        stableActiveResume &&
          createResumeFingerprint(stableActiveResume) !==
            lastPersistedResumeRef.current,
      );
    }

    if (isTemplateDetailView && !activeTemplateDefinition.isBuiltIn) {
      return (
        createTemplateFingerprint(activeTemplateDefinition) !==
        lastPersistedTemplateRef.current
      );
    }

    return false;
  }, [
    activeTemplateDefinition,
    buildActiveResumeItem,
    isResumeDetailView,
    isTemplateDetailView,
    lastSavedAt,
    saveState,
  ]);

  const restorePersistedActiveResume = useCallback(() => {
    const persistedResume = lastPersistedResumeItemRef.current;

    if (!persistedResume || persistedResume.id !== activeResumeId) {
      return;
    }

    setResumeDocuments((current) =>
      current.map((item) =>
        item.id === persistedResume.id ? persistedResume : item,
      ),
    );
    hydrateResumeWorkspace(persistedResume);
    lastPersistedResumeRef.current = createResumeFingerprint(persistedResume);
    setSaveState("saved");
  }, [activeResumeId, hydrateResumeWorkspace]);

  const restorePersistedActiveTemplate = useCallback(() => {
    const persistedTemplate = lastPersistedTemplateItemRef.current;

    if (
      !persistedTemplate ||
      !isTemplateDetailView ||
      activeTemplateDefinition.isBuiltIn ||
      persistedTemplate.id !== activeTemplateDefinition.id
    ) {
      return;
    }

    setCustomTemplates((current) =>
      current.map((item) =>
        item.id === persistedTemplate.id ? persistedTemplate : item,
      ),
    );
    lastPersistedTemplateRef.current =
      createTemplateFingerprint(persistedTemplate);
    setSaveState("saved");
  }, [
    activeTemplateDefinition,
    isTemplateDetailView,
  ]);

  const requestWorkspaceLeave = useCallback(
    (run: () => void) => {
      if (!hasUnsavedCurrentWorkspaceChanges()) {
        run();
        return;
      }

      setPendingWorkspaceLeaveAction({ run });
    },
    [hasUnsavedCurrentWorkspaceChanges],
  );

  useEffect(() => {
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasUnsavedCurrentWorkspaceChanges()) {
        return;
      }

      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [hasUnsavedCurrentWorkspaceChanges]);

  const loadWorkspace = useCallback(
    async () => {
      setIsLoading(true);
      setHasLoadError(false);

      try {
        const [
          payload,
          resumesPayload,
          deletedResumesPayload,
          templatesPayload,
          deletedTemplatesPayload,
        ] = await Promise.all([
          fetchWorkspaceBootstrap(initialLocaleRef.current),
          fetchResumesApi(),
          fetchDeletedResumesApi(),
          fetchTemplatesApi(),
          fetchDeletedTemplatesApi(),
        ]);
        const workspaceSource = payload.workspace;
        const resumeWorkspaceSource = {
          ...workspaceSource,
          resumes: resumesPayload.resumes,
          deletedResumes: deletedResumesPayload.resumes,
        };
        const templateWorkspaceSource = {
          ...workspaceSource,
          customTemplates: templatesPayload.templates,
          deletedTemplates: deletedTemplatesPayload.templates,
        };
        const requestedDefaultTemplateId =
          workspaceSource &&
          typeof workspaceSource === "object" &&
          "defaultTemplateId" in workspaceSource &&
          typeof (workspaceSource as { defaultTemplateId?: unknown })
            .defaultTemplateId === "string" &&
          (
            workspaceSource as { defaultTemplateId: string }
          ).defaultTemplateId.trim()
            ? (workspaceSource as { defaultTemplateId: string })
                .defaultTemplateId
            : defaultTemplate;
        const nextDocuments = normalizeResumeDocuments(
          resumeWorkspaceSource,
          initialLocaleRef.current,
          requestedDefaultTemplateId,
        );
        const nextModelConfigs = normalizeModelConfigs(
          workspaceSource,
          initialLocaleRef.current,
        );
        const nextCustomTemplates = normalizeCustomTemplates(
          templateWorkspaceSource,
        );
        const nextDeletedResumes = normalizeDeletedResumeDocuments(
          resumeWorkspaceSource,
          requestedDefaultTemplateId,
        );
        const nextDeletedTemplates = normalizeDeletedTemplates(
          templateWorkspaceSource,
        );
        const nextAgentSettings = normalizeAgentSettings(
          workspaceSource?.agentSettings,
          nextModelConfigs,
        );
        const nextTheme = normalizeWorkspaceTheme(workspaceSource?.theme);
        const firstResume = nextDocuments[0] ?? null;
        const versionsPayload = firstResume
          ? await fetchResumeVersionsApi(firstResume.id).catch(() => ({
              versions: [] as WorkspaceVersionSummary[],
            }))
          : { versions: [] as WorkspaceVersionSummary[] };

        setResumeDocuments(nextDocuments);
        setActiveResumeId(firstResume?.id ?? null);
        setShowResumeGallery(true);
        if (firstResume) {
          hydrateResumeWorkspace(firstResume);
        } else {
          resetResumeWorkspace();
        }
        setDefaultTemplateId(requestedDefaultTemplateId);
        setCustomTemplates(nextCustomTemplates);
        setDeletedResumeDocuments(nextDeletedResumes);
        setDeletedTemplates(nextDeletedTemplates);
        setModelConfigs(nextModelConfigs);
        setAgentSettings(nextAgentSettings);
        setTheme(nextTheme);
        persistedUserSettingsRef.current = {
          locale: initialLocaleRef.current,
          theme: nextTheme,
          agentSettings: nextAgentSettings,
        };
        setLastSavedAt(payload.savedAt);
        lastPersistedResumeRef.current = createResumeFingerprint(firstResume);
        lastPersistedResumeItemRef.current = firstResume;
        lastPersistedTemplateRef.current = null;
        lastPersistedTemplateItemRef.current = null;
        lastOpenedTemplateIdRef.current = null;
        setWorkspaceVersions(versionsPayload.versions);
        setActiveWorkspaceVersionId(
          versionsPayload.versions[0]?.versionId ?? null,
        );
        setSaveState(payload.savedAt ? "saved" : "idle");
      } catch (error) {
        console.error("Failed to load workspace from backend.", error);
        setSaveState("idle");
        setHasLoadError(true);
      } finally {
        setIsLoading(false);
      }
    },
    [hydrateResumeWorkspace, resetResumeWorkspace],
  );

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  const loadResumeDetail = useCallback(
    async (resumeId: string) => {
      if (resumeDetailRequestRef.current === resumeId) {
        return;
      }

      resumeDetailRequestRef.current = resumeId;

      try {
        const [detail, versionsPayload] = await Promise.all([
          fetchResumeApi(resumeId),
          fetchResumeVersionsApi(resumeId).catch(() => ({
            versions: [] as WorkspaceVersionSummary[],
          })),
        ]);

        setResumeDocuments((current) => {
          const hasResume = current.some((item) => item.id === detail.resume.id);

          if (!hasResume) {
            return [detail.resume, ...current];
          }

          return current.map((item) =>
            item.id === detail.resume.id ? detail.resume : item,
          );
        });
        hydrateResumeWorkspace(detail.resume);
        setLastSavedAt(detail.savedAt);
        setActiveWorkspaceVersionId(detail.versionId);
        setWorkspaceVersions(versionsPayload.versions);
        lastPersistedResumeRef.current = createResumeFingerprint(detail.resume);
        lastPersistedResumeItemRef.current = detail.resume;
        lastLoadedResumeDetailIdRef.current = detail.resume.id;
        setHasLoadError(false);
      } catch (error) {
        console.error("Failed to load resume detail.", error);
        setHasLoadError(true);
      } finally {
        resumeDetailRequestRef.current = null;
      }
    },
    [hydrateResumeWorkspace],
  );

  useEffect(() => {
    if (isLoading) {
      return;
    }

    switch (currentRoute.kind) {
      case "resume-gallery": {
        setActiveView("resume");
        setShowResumeGallery(true);
        return;
      }
      case "resume-detail": {
        const targetResume = resumeDocuments.find(
          (item) => item.id === currentRoute.id,
        );

        if (!targetResume) {
          navigate("/resume", { replace: true });
          return;
        }

        setActiveView("resume");
        setShowResumeGallery(false);

        if (activeResumeId !== targetResume.id) {
          setActiveResumeId(targetResume.id);
          hydrateResumeWorkspace(targetResume);
        }
        if (lastLoadedResumeDetailIdRef.current !== targetResume.id) {
          void loadResumeDetail(targetResume.id);
        }
        return;
      }
      case "template-gallery": {
        setActiveView("templates");
        setShowTemplateGallery(true);
        return;
      }
      case "template-detail": {
        const targetTemplate = templateCatalog.find(
          (item) => item.id === currentRoute.id,
        );

        if (!targetTemplate) {
          navigate("/templates", { replace: true });
          return;
        }

        setActiveView("templates");
        setShowTemplateGallery(false);

        if (template !== targetTemplate.id) {
          setTemplate(targetTemplate.id);
        }
        if (lastOpenedTemplateIdRef.current !== targetTemplate.id) {
          lastOpenedTemplateIdRef.current = targetTemplate.id;
          lastPersistedTemplateRef.current = targetTemplate.isBuiltIn
            ? null
            : createTemplateFingerprint(targetTemplate);
          lastPersistedTemplateItemRef.current = targetTemplate.isBuiltIn
            ? null
            : targetTemplate;
        }
        return;
      }
      case "trash": {
        setActiveView("trash");
        return;
      }
      case "models": {
        setActiveView("models");
        return;
      }
      case "settings": {
        setActiveView("settings");
        return;
      }
      case "unknown":
      default: {
        navigate("/resume", { replace: true });
      }
    }
  }, [
    activeResumeId,
    currentRoute,
    hydrateResumeWorkspace,
    isLoading,
    loadResumeDetail,
    navigate,
    resumeDocuments,
    template,
    templateCatalog,
  ]);

  function openResumeTitleDialog() {
    setResumeTitleDraft(activeResumeTitle || t.untitledResume);
    setIsResumeTitleDialogOpen(true);
  }

  function saveActiveResumeTitle() {
    if (!activeResumeId) {
      return;
    }

    setResumeDocuments((current) =>
      current.map((item, index) => {
        if (item.id !== activeResumeId) {
          return item;
        }

        const fallbackTitle =
          item.resume.basic.name ||
          createDefaultResumeTitle(t, index + 1) ||
          t.untitledResume;
        const nextTitle = normalizeResumeTitle(resumeTitleDraft, fallbackTitle);

        if (nextTitle === item.title) {
          return item;
        }

        return {
          ...item,
          title: nextTitle,
          updatedAt: new Date().toISOString(),
        };
      }),
    );
    setIsResumeTitleDialogOpen(false);
  }

  async function selectWorkspaceVersion(versionId: string) {
    if (
      !activeResumeId ||
      versionId === activeWorkspaceVersionId ||
      versionLoadRequestRef.current === versionId ||
      saveState === "saving"
    ) {
      return;
    }

    versionLoadRequestRef.current = versionId;
    setIsLoading(true);
    setHasLoadError(false);

    try {
      const result = await fetchResumeVersionApi(activeResumeId, versionId);
      const nextActiveResume = result.resume;

      setResumeDocuments((current) =>
        current.map((item) =>
          item.id === nextActiveResume.id ? nextActiveResume : item,
        ),
      );
      hydrateResumeWorkspace(nextActiveResume);
      setLastSavedAt(result.savedAt);
      setActiveWorkspaceVersionId(result.versionId);
      lastPersistedResumeRef.current =
        createResumeFingerprint(nextActiveResume);
      lastPersistedResumeItemRef.current = nextActiveResume;
      setSaveState("saved");

      if (isResumeDetailView) {
        navigate(getResumePath(nextActiveResume.id), { replace: true });
      }
    } catch (error) {
      console.error("Failed to load resume version.", error);
      setHasLoadError(true);
      setSaveState("idle");
    } finally {
      versionLoadRequestRef.current = null;
      setIsLoading(false);
    }
  }

  async function saveAndRunPendingWorkspaceLeaveAction() {
    if (!pendingWorkspaceLeaveAction || isResolvingWorkspaceLeave) {
      return;
    }

    const action = pendingWorkspaceLeaveAction.run;

    setIsResolvingWorkspaceLeave(true);

    try {
      await saveCurrentWorkspace();
      setPendingWorkspaceLeaveAction(null);
      action();
    } catch (error) {
      console.error("Failed to save workspace before leaving.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
    } finally {
      setIsResolvingWorkspaceLeave(false);
    }
  }

  function discardAndRunPendingWorkspaceLeaveAction() {
    if (!pendingWorkspaceLeaveAction || isResolvingWorkspaceLeave) {
      return;
    }

    const action = pendingWorkspaceLeaveAction.run;

    restorePersistedActiveResume();
    restorePersistedActiveTemplate();
    setPendingWorkspaceLeaveAction(null);
    action();
  }

  const persistUserSettings = useCallback(
    (
      nextLocale: Locale,
      nextTheme: ThemeMode,
      nextAgentSettings: AgentSettings,
    ) => {
      if (isLoading) {
        return;
      }

      const mutationId = ++userSettingsMutationIdRef.current;
      const snapshot: UserSettingsSnapshot = {
        locale: nextLocale,
        theme: nextTheme,
        agentSettings: nextAgentSettings,
      };

      // Serialize full-snapshot writes so a slower request cannot overwrite a newer
      // settings choice. The queue remains usable after an individual save fails.
      const request = userSettingsSaveQueueRef.current.then(async () => {
        await saveUserSettingsApi(snapshot.locale, {
          agentSettings: snapshot.agentSettings,
          theme: snapshot.theme,
        });
        persistedUserSettingsRef.current = snapshot;
      });
      userSettingsSaveQueueRef.current = request.catch(() => undefined);

      void request.catch((error) => {
        console.error("Failed to save user settings.", error);
        if (userSettingsMutationIdRef.current === mutationId) {
          const persisted = persistedUserSettingsRef.current;
          onLocaleChange(persisted.locale);
          setTheme(persisted.theme);
          setAgentSettings(
            normalizeAgentSettings(persisted.agentSettings, modelConfigs),
          );
        }
        if (!isApiErrorToastShown(error)) {
          toast.error(t.loadError, {
            closeButton: true,
          });
        }
      });
    },
    [isLoading, modelConfigs, onLocaleChange, t.loadError],
  );

  const flushUserSettings = useCallback(
    () => userSettingsSaveQueueRef.current,
    [],
  );

  const handleSettingsLocaleChange = useCallback(
    (nextLocale: Locale) => {
      onLocaleChange(nextLocale);
      persistUserSettings(nextLocale, theme, agentSettings);
    },
    [agentSettings, onLocaleChange, persistUserSettings, theme],
  );

  const handleSettingsThemeChange = useCallback(
    (nextTheme: ThemeMode) => {
      setTheme(nextTheme);
      persistUserSettings(locale, nextTheme, agentSettings);
    },
    [agentSettings, locale, persistUserSettings],
  );

  const handleAgentSettingsChange = useCallback(
    (nextSettings: AgentSettings) => {
      const normalizedSettings = normalizeAgentSettings(nextSettings, modelConfigs);
      setAgentSettings(normalizedSettings);
      persistUserSettings(locale, theme, normalizedSettings);
    },
    [locale, modelConfigs, persistUserSettings, theme],
  );

  const handleModelConfigsChange = useCallback(
    (nextModelConfigs: ModelConfig[]) => {
      const normalizedSettings = normalizeAgentSettings(
        agentSettings,
        nextModelConfigs,
      );

      setModelConfigs(nextModelConfigs);
      if (
        normalizedSettings.defaultModelId !== agentSettings.defaultModelId
      ) {
        setAgentSettings(normalizedSettings);
        persistUserSettings(locale, theme, normalizedSettings);
      }
    },
    [agentSettings, locale, persistUserSettings, theme],
  );

  useEffect(() => {
    const hasActiveTemplate = templateCatalog.some(
      (item) => item.id === template,
    );
    const hasDefaultTemplate = templateCatalog.some(
      (item) => item.id === defaultTemplateId,
    );

    if (!hasActiveTemplate) {
      setTemplate(hasDefaultTemplate ? defaultTemplateId : defaultTemplate);
    }

    if (!hasDefaultTemplate) {
      setDefaultTemplateId(defaultTemplate);
    }
  }, [defaultTemplateId, template, templateCatalog]);

  function openResumeEditor(resumeId: string) {
    requestWorkspaceLeave(() => {
      const targetResume = resumeDocuments.find((item) => item.id === resumeId);

      if (!targetResume) {
        return;
      }

      setActiveResumeId(resumeId);
      hydrateResumeWorkspace(targetResume);
      lastLoadedResumeDetailIdRef.current = null;
      setActiveView("resume");
      setShowResumeGallery(false);
      runViewTransition(() => navigate(getResumePath(resumeId)), "nav-forward");
      void loadResumeDetail(resumeId);
    });
  }

  function openTemplateEditor(templateId: string) {
    requestWorkspaceLeave(() => {
      if (!templateCatalog.some((item) => item.id === templateId)) {
        return;
      }

      setTemplate(templateId);
      setActiveView("templates");
      setShowTemplateGallery(false);
      runViewTransition(
        () => navigate(getTemplatePath(templateId)),
        "nav-forward",
      );
    });
  }

  async function createResume() {
    if (
      isLoading ||
      saveState === "saving" ||
      createResumeInFlightRef.current
    ) {
      return;
    }

    createResumeInFlightRef.current = true;
    setIsCreatingResume(true);

    try {
      await saveCurrentWorkspace();

      const result = await createResumeApi({
        title: createDefaultResumeTitle(t, resumeDocuments.length + 1),
        template: defaultTemplateId,
      });
      const nextItem = result.resume;

      setResumeDocuments((current) => [...current, nextItem]);
      setActiveResumeId(nextItem.id);
      hydrateResumeWorkspace(nextItem);
      lastPersistedResumeRef.current = createResumeFingerprint(nextItem);
      lastPersistedResumeItemRef.current = nextItem;
      lastLoadedResumeDetailIdRef.current = nextItem.id;
      setLastSavedAt(result.savedAt);
      setActiveWorkspaceVersionId(result.versionId);
      setWorkspaceVersions([{ versionId: result.versionId, savedAt: result.savedAt }]);
      setSaveState("saved");
      setActiveView("resume");
      setShowResumeGallery(false);
      runViewTransition(
        () => navigate(getResumePath(nextItem.id)),
        "nav-forward",
      );
    } catch (error) {
      console.error("Failed to create resume in backend.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
      return;
    } finally {
      createResumeInFlightRef.current = false;
      setIsCreatingResume(false);
    }
  }

  async function duplicateActiveResume() {
    if (
      !activeResumeId ||
      isLoading ||
      saveState === "saving" ||
      duplicateResumeInFlightRef.current
    ) {
      return;
    }

    const sourceResumeId = activeResumeId;
    duplicateResumeInFlightRef.current = true;
    setIsDuplicatingResume(true);

    try {
      await saveCurrentWorkspace();
      const result = await duplicateResumeApi(sourceResumeId, locale);
      const nextItem = result.resume;

      setResumeDocuments((current) => [...current, nextItem]);
      setActiveResumeId(nextItem.id);
      hydrateResumeWorkspace(nextItem);
      lastPersistedResumeRef.current = createResumeFingerprint(nextItem);
      lastPersistedResumeItemRef.current = nextItem;
      lastLoadedResumeDetailIdRef.current = nextItem.id;
      setLastSavedAt(result.savedAt);
      setActiveWorkspaceVersionId(result.versionId);
      setWorkspaceVersions([
        { versionId: result.versionId, savedAt: result.savedAt },
      ]);
      setSaveState("saved");
      setActiveView("resume");
      setShowResumeGallery(false);
      runViewTransition(
        () => navigate(getResumePath(nextItem.id)),
        "nav-forward",
      );
      toast.success(t.resumeDuplicated, {
        closeButton: true,
      });
    } catch (error) {
      console.error("Failed to duplicate resume.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.duplicateResumeFailed, {
          closeButton: true,
        });
      }
    } finally {
      duplicateResumeInFlightRef.current = false;
      setIsDuplicatingResume(false);
    }
  }

  async function importResume(file: File) {
    // The ref closes the same-render re-entry gap before React commits the
    // disabled button state. Resume and template imports share one lock.
    if (importInFlightRef.current) {
      return;
    }

    importInFlightRef.current = true;
    setIsImporting(true);

    try {
      const isPdfImport =
        file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
      const importedDocuments = isPdfImport
        ? [
            {
              id: createId("import"),
              title: normalizeResumeTitle(
                file.name.replace(/\.pdf$/i, ""),
                createDefaultResumeTitle(t, resumeDocuments.length + 1),
              ),
              updatedAt: new Date().toISOString(),
              resume: await importResumeFromPdf(
                file,
                t.importedResumeFallbackSection,
              ),
              jobBrief: "",
              typography: defaultTypography,
              template: defaultTemplateId,
              templateSettings: undefined,
            },
          ]
        : normalizeImportedResumeDocuments(
            await importResumePayload(file),
            defaultTemplateId,
          );

      if (importedDocuments.length === 0) {
        throw new Error(
          "No valid resume documents found in the imported file.",
        );
      }

      await saveCurrentWorkspace();

      const savedImports: Array<{
        resume: ResumeWorkspaceItem;
        savedAt: string;
        versionId: string;
      }> = [];
      for (const item of importedDocuments) {
        const result = await createResumeApi({
          title: item.title,
          resume: item.resume,
          jobBrief: item.jobBrief,
          typography: item.typography,
          template: item.template,
          templateSettings: item.templateSettings ?? null,
        });
        savedImports.push(result);
      }

      const firstImportedResume = savedImports[0]?.resume;

      if (!firstImportedResume) {
        throw new Error("Failed to save imported resume.");
      }

      setResumeDocuments((current) => [
        ...current,
        ...savedImports.map((item) => item.resume),
      ]);
      setActiveResumeId(firstImportedResume.id);
      hydrateResumeWorkspace(firstImportedResume);
      lastPersistedResumeRef.current =
        createResumeFingerprint(firstImportedResume);
      lastPersistedResumeItemRef.current = firstImportedResume;
      lastLoadedResumeDetailIdRef.current = firstImportedResume.id;
      setLastSavedAt(savedImports[0].savedAt);
      setActiveWorkspaceVersionId(savedImports[0].versionId);
      setWorkspaceVersions([
        {
          versionId: savedImports[0].versionId,
          savedAt: savedImports[0].savedAt,
        },
      ]);
      setSaveState("saved");
      setActiveView("resume");
      setShowResumeGallery(false);
      runViewTransition(
        () => navigate(getResumePath(firstImportedResume.id)),
        "nav-forward",
      );
      toast.success(t.importResumeSuccess, {
        closeButton: true,
      });
    } catch (error) {
      console.error("Failed to import resume.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.importResumeFailed, {
          closeButton: true,
        });
      }
    } finally {
      importInFlightRef.current = false;
      setIsImporting(false);
    }
  }

  const clearRejectedAgentDraft = useCallback(
    (sourceMessageId?: string) => {
      const shouldClear = (draft: AgentDraftState | null) =>
        Boolean(
          draft &&
            draft.status === "pending" &&
            (!sourceMessageId || draft.sourceMessageId === sourceMessageId),
        );

      setAgentDraft((draft) => {
        if (!shouldClear(draft)) {
          return draft;
        }
        if (agentDraftBaseRef.current?.draftId === draft?.id) {
          agentDraftBaseRef.current = null;
        }
        return null;
      });
      setLastAgentDraft((draft) => (shouldClear(draft) ? null : draft));
    },
    [],
  );

  const previewAgentEdits = useCallback(
    (
      edits: AgentResumeEditSuggestion[],
      baseResume: ResumeData,
      sourceMessageId?: string,
      transactionState: AgentTransactionState = "committed",
    ) => {
      const draftBase = createAgentDraftBaseSnapshot(baseResume);
      const result = applyAgentEditsWithMerge(
        draftBase,
        currentResumeRef.current,
        edits,
      );

      if (result.errors.length > 0) {
        // Provisional batches are replaced as the tool keeps streaming. Only
        // surface a conflict once the backend has committed its final batch.
        if (transactionState === "committed") {
          clearRejectedAgentDraft(sourceMessageId);
          toast.error(t.agentDraftBatchRejected, {
            description: formatAgentDraftErrors(result.errors, t),
            closeButton: true,
          });
        }
        return;
      }

      if (result.appliedCount === 0) {
        if (transactionState === "committed") {
          clearRejectedAgentDraft(sourceMessageId);
        }
        return;
      }

      const now = new Date().toISOString();
      const draftId = sourceMessageId
        ? `agent-draft-${sourceMessageId}`
        : createId("agent-draft");
      const nextDraft: AgentDraftState = {
        id: draftId,
        status: "pending",
        sourceMessageId,
        createdAt: agentDraft?.id === draftId ? agentDraft.createdAt : now,
        updatedAt: now,
        resume: result.resume,
        editCount: result.appliedCount,
        edits,
        diffs: result.diffs,
        transactionState,
      };

      agentDraftBaseRef.current = {
        draftId,
        resume: draftBase,
      };
      setAgentDraft(nextDraft);
      setLastAgentDraft(nextDraft);
    },
    [
      agentDraft?.createdAt,
      agentDraft?.id,
      clearRejectedAgentDraft,
      t,
    ],
  );

  const rollbackAgentDraft = useCallback((sourceMessageId?: string) => {
    const shouldRollback = (draft: AgentDraftState | null) =>
      Boolean(
        draft &&
          draft.status === "pending" &&
          (sourceMessageId
            ? draft.sourceMessageId === sourceMessageId
            : draft.transactionState === "provisional"),
      );

    setAgentDraft((draft) => {
      if (!shouldRollback(draft)) {
        return draft;
      }

      if (agentDraftBaseRef.current?.draftId === draft?.id) {
        agentDraftBaseRef.current = null;
      }
      return null;
    });
    setLastAgentDraft((draft) => (shouldRollback(draft) ? null : draft));
  }, []);

  const applyAgentDraft = useCallback(() => {
    if (!agentDraft || agentDraft.transactionState !== "committed") {
      return;
    }

    const draftBase = agentDraftBaseRef.current;
    if (!draftBase || draftBase.draftId !== agentDraft.id) {
      return;
    }

    const result = applyAgentEditsWithMerge(
      draftBase.resume,
      currentResumeRef.current,
      agentDraft.edits,
    );

    if (result.errors.length > 0) {
      toast.error(t.agentDraftBatchRejected, {
        description: formatAgentDraftErrors(result.errors, t),
        closeButton: true,
      });
      return;
    }

    setResume(result.resume);
    setCollapsedState(createEditorCollapsedState(result.resume));
    setLastAgentDraft({
      ...agentDraft,
      status: "applied",
      updatedAt: new Date().toISOString(),
      resume: result.resume,
    });
    agentDraftBaseRef.current = null;
    setAgentDraft(null);
    toast.success(t.agentDraftApplied, {
      closeButton: true,
    });
  }, [agentDraft, t]);

  const discardAgentDraft = useCallback(() => {
    if (!agentDraft || agentDraft.transactionState !== "committed") {
      return;
    }

    setLastAgentDraft({
      ...agentDraft,
      status: "discarded",
      updatedAt: new Date().toISOString(),
    });
    agentDraftBaseRef.current = null;
    setAgentDraft(null);
    toast.success(t.agentDraftDiscarded, {
      closeButton: true,
    });
  }, [agentDraft, t]);

  async function moveResumesToTrash(resumeIds: string[]) {
    if (resumeIds.length === 0) {
      return;
    }

    const removing = resumeDocuments.filter((item) =>
      resumeIds.includes(item.id),
    );
    const remaining = resumeDocuments.filter(
      (item) => !resumeIds.includes(item.id),
    );

    if (removing.length === 0) {
      return;
    }

    let deletedItems: DeletedResumeWorkspaceItem[];
    try {
      const results = [];
      for (const resumeId of resumeIds) {
        results.push(await moveResumeToTrashApi(resumeId));
      }
      deletedItems = results.map((item) => item.resume);
    } catch (error) {
      console.error("Failed to move resume to trash.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
      return;
    }

    const nextActiveResume =
      remaining.find((item) => item.id === activeResumeId) ??
      remaining[0] ??
      null;
    const removedActiveResume =
      activeResumeId !== null && resumeIds.includes(activeResumeId);
    const removedRouteResume =
      currentRoute.kind === "resume-detail" &&
      resumeIds.includes(currentRoute.id);

    setResumeDocuments(remaining);
    setDeletedResumeDocuments((previous) => [
      ...deletedItems,
      ...previous,
    ]);

    if (removedRouteResume) {
      setActiveResumeId(nextActiveResume?.id ?? null);

      if (nextActiveResume) {
        hydrateResumeWorkspace(nextActiveResume);
      } else {
        setShowResumeGallery(true);
      }

      runViewTransition(
        () =>
          navigate(
            nextActiveResume ? getResumePath(nextActiveResume.id) : "/resume",
          ),
        nextActiveResume ? "nav-forward" : "nav-back",
      );
    } else if (removedActiveResume) {
      setActiveResumeId(null);
    }

    toast.success(resumeIds.length > 1 ? t.resumesDeleted : t.resumeDeleted, {
      closeButton: true,
    });
  }

  async function restoreResumes(resumeIds: string[]) {
    if (resumeIds.length === 0) {
      return false;
    }

    if (!deletedResumeDocuments.some((item) => resumeIds.includes(item.id))) {
      return false;
    }

    let restoredItems: ResumeWorkspaceItem[];
    try {
      const results = [];
      for (const resumeId of resumeIds) {
        results.push(await restoreResumeApi(resumeId));
      }
      restoredItems = results.map((item) => item.resume);
    } catch (error) {
      console.error("Failed to restore resume.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
      return false;
    }

    startTransition(() => {
      setDeletedResumeDocuments((current) =>
        current.filter((item) => !resumeIds.includes(item.id)),
      );
      setResumeDocuments((current) => [...restoredItems, ...current]);
    });

    toast.success(resumeIds.length > 1 ? t.resumesRestored : t.resumeRestored, {
      closeButton: true,
    });
    return true;
  }

  async function permanentlyDeleteResumes(resumeIds: string[]) {
    if (resumeIds.length === 0) {
      return false;
    }

    try {
      for (const resumeId of resumeIds) {
        await deleteResumeForeverApi(resumeId);
      }
    } catch (error) {
      console.error("Failed to permanently delete resume.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
      return false;
    }

    startTransition(() => {
      setDeletedResumeDocuments((current) =>
        current.filter((item) => !resumeIds.includes(item.id)),
      );
    });
    toast.success(
      resumeIds.length > 1 ? t.resumesDeletedForever : t.resumeDeletedForever,
      {
        closeButton: true,
      },
    );
    return true;
  }

  async function createCustomTemplate() {
    if (
      isLoading ||
      saveState === "saving" ||
      createTemplateInFlightRef.current
    ) {
      return;
    }

    createTemplateInFlightRef.current = true;
    setIsCreatingTemplate(true);

    const draftTemplate = createCustomTemplateFromBase(
      activeTemplateDefinition,
      {
        name: `${t.customTemplate} ${customTemplates.length + 1}`,
      },
    );

    try {
      await saveCurrentWorkspace();

      const result = await createTemplateApi(draftTemplate);
      const nextTemplate = result.template;

      setCustomTemplates((current) => [...current, nextTemplate]);
      setTemplate(nextTemplate.id);
      lastPersistedTemplateRef.current = createTemplateFingerprint(nextTemplate);
      lastPersistedTemplateItemRef.current = nextTemplate;
      lastOpenedTemplateIdRef.current = nextTemplate.id;
      setLastSavedAt(nextTemplate.updatedAt);
      setActiveView("templates");
      setShowTemplateGallery(false);
      runViewTransition(
        () => navigate(getTemplatePath(nextTemplate.id)),
        "nav-forward",
      );
      toast.success(t.templateCreated, {
        closeButton: true,
      });
    } catch (error) {
      console.error("Failed to create template in backend.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
    } finally {
      createTemplateInFlightRef.current = false;
      setIsCreatingTemplate(false);
    }
  }

  async function importTemplates(file: File) {
    if (importInFlightRef.current) {
      return;
    }

    importInFlightRef.current = true;
    setIsImporting(true);

    try {
      const payload = await importTemplatePayload(file);
      const importedTemplates = normalizeCustomTemplates(payload).map(
        (item, index) => ({
          ...item,
          id: createId("template"),
          name:
            item.name.trim() ||
            `${t.customTemplate} ${customTemplates.length + index + 1}`,
          updatedAt: new Date().toISOString(),
          isBuiltIn: false,
        }),
      );

      if (importedTemplates.length === 0) {
        throw new Error("No valid templates found in imported file.");
      }

      await saveCurrentWorkspace();

      const savedImports: ResumeTemplateDefinition[] = [];
      for (const item of importedTemplates) {
        const result = await createTemplateApi(item);
        savedImports.push(result.template);
      }

      const firstImportedTemplate = savedImports[0];

      if (!firstImportedTemplate) {
        throw new Error("Failed to save imported template.");
      }

      setCustomTemplates((current) => [...current, ...savedImports]);
      setTemplate(firstImportedTemplate.id);
      lastPersistedTemplateRef.current =
        createTemplateFingerprint(firstImportedTemplate);
      lastPersistedTemplateItemRef.current = firstImportedTemplate;
      lastOpenedTemplateIdRef.current = firstImportedTemplate.id;
      setLastSavedAt(firstImportedTemplate.updatedAt);
      setActiveView("templates");
      setShowTemplateGallery(false);
      runViewTransition(
        () => navigate(getTemplatePath(firstImportedTemplate.id)),
        "nav-forward",
      );
      toast.success(t.templateImported, {
        closeButton: true,
      });
    } catch (error) {
      console.error("Failed to import template JSON.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.templateImportFailed, {
          closeButton: true,
        });
      }
    } finally {
      importInFlightRef.current = false;
      setIsImporting(false);
    }
  }

  function updateCustomTemplate(
    templateId: string,
    patch: Partial<ResumeTemplateDefinition>,
  ) {
    setCustomTemplates((current) =>
      current.map((item) =>
        item.id === templateId
          ? {
              ...item,
              ...patch,
              settings: patch.settings
                ? patch.preset
                  ? createTemplateSettings(patch.preset, patch.settings)
                  : patch.settings
                : patch.preset
                  ? createTemplateSettings(patch.preset)
                  : item.settings,
              layout: patch.layout
                ? patch.preset
                  ? createTemplateLayout(patch.preset, patch.layout)
                  : patch.layout
                : patch.preset
                  ? createTemplateLayout(patch.preset)
                  : item.layout,
              updatedAt: new Date().toISOString(),
            }
          : item,
      ),
    );
  }

  function moveTemplateImage(
    imageId: string,
    patch: Pick<ResumeTemplateImageElement, "x" | "y">,
  ) {
    if (activeView !== "templates" || activeTemplateDefinition.isBuiltIn) {
      return;
    }

    updateCustomTemplate(activeTemplateDefinition.id, {
      layout: {
        ...activeTemplateDefinition.layout,
        images: (activeTemplateDefinition.layout.images ?? []).map((image) =>
          image.id === imageId ? { ...image, ...patch } : image,
        ),
      },
    });
  }

  async function deleteTemplates(templateIds: string[]) {
    if (templateIds.length === 0) {
      return;
    }

    const customTemplateIds = templateIds.filter((templateId) =>
      customTemplates.some((item) => item.id === templateId),
    );

    if (customTemplateIds.length === 0) {
      return;
    }

    let deletedItems: DeletedResumeTemplateDefinition[];
    try {
      const results = [];
      for (const templateId of customTemplateIds) {
        results.push(await moveTemplateToTrashApi(templateId));
      }
      deletedItems = results.map((item) => item.template);
    } catch (error) {
      console.error("Failed to move template to trash.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
      return;
    }

    setCustomTemplates((current) =>
      current.filter((item) => !customTemplateIds.includes(item.id)),
    );
    setDeletedTemplates((current) => [...deletedItems, ...current]);

    if (customTemplateIds.includes(defaultTemplateId)) {
      setDefaultTemplateId(defaultTemplate);
    }

      if (customTemplateIds.includes(template)) {
        const fallbackTemplateId = customTemplateIds.includes(defaultTemplateId)
          ? defaultTemplate
          : defaultTemplateId;
        setTemplate(fallbackTemplateId);
        lastPersistedTemplateRef.current = null;
        lastPersistedTemplateItemRef.current = null;
        lastOpenedTemplateIdRef.current = null;
      }

    toast.success(
      customTemplateIds.length > 1 ? t.templatesDeleted : t.templateDeleted,
      {
        closeButton: true,
      },
    );
  }

  async function restoreTemplates(templateIds: string[]) {
    if (templateIds.length === 0) {
      return false;
    }

    const restoring = deletedTemplates.filter((item) =>
      templateIds.includes(item.id),
    );

    if (restoring.length === 0) {
      return false;
    }

    let restoredItems: ResumeTemplateDefinition[];
    try {
      const results = [];
      for (const templateId of templateIds) {
        results.push(await restoreTemplateApi(templateId));
      }
      restoredItems = results.map((item) => item.template);
    } catch (error) {
      console.error("Failed to restore template.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
      return false;
    }

    startTransition(() => {
      setDeletedTemplates((current) =>
        current.filter((item) => !templateIds.includes(item.id)),
      );
      setCustomTemplates((current) => [...restoredItems, ...current]);
    });

    toast.success(
      templateIds.length > 1 ? t.templatesRestored : t.templateRestored,
      {
        closeButton: true,
      },
    );
    return true;
  }

  async function permanentlyDeleteTemplates(templateIds: string[]) {
    if (templateIds.length === 0) {
      return false;
    }

    try {
      for (const templateId of templateIds) {
        await deleteTemplateForeverApi(templateId);
      }
    } catch (error) {
      console.error("Failed to permanently delete template.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
      return false;
    }

    startTransition(() => {
      setDeletedTemplates((current) =>
        current.filter((item) => !templateIds.includes(item.id)),
      );
    });
    toast.success(
      templateIds.length > 1
        ? t.templatesDeletedForever
        : t.templateDeletedForever,
      {
        closeButton: true,
      },
    );
    return true;
  }

  async function handleSetDefaultTemplate(templateId: string) {
    if (
      templateId === defaultTemplateId ||
      setDefaultTemplateInFlightRef.current ||
      !templateCatalog.some((item) => item.id === templateId)
    ) {
      return;
    }

    setDefaultTemplateInFlightRef.current = true;
    setSettingDefaultTemplateId(templateId);

    try {
      const result = await saveDefaultTemplateApi(templateId);
      setDefaultTemplateId(result.defaultTemplateId);
      toast.success(t.defaultTemplateUpdated, {
        closeButton: true,
      });
    } catch (error) {
      console.error("Failed to update default template.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
    } finally {
      setDefaultTemplateInFlightRef.current = false;
      setSettingDefaultTemplateId(null);
    }
  }

  function applyTemplateToActiveResume(templateId: string) {
    const targetTemplate = templateCatalog.find((item) => item.id === templateId);

    if (!targetTemplate) {
      return;
    }

    if (
      templateId === template &&
      targetTemplate.typography.fontFamily === typography.fontFamily &&
      targetTemplate.typography.fontSize === typography.fontSize
    ) {
      return;
    }

    setTemplate(templateId);
    setTypography(targetTemplate.typography);
    setTemplateSettings(targetTemplate.settings);

    if (!activeResumeId) {
      return;
    }

    setResumeDocuments((current) =>
      current.map((item) =>
        item.id === activeResumeId
          ? {
              ...item,
              template: templateId,
              typography: targetTemplate.typography,
              templateSettings: targetTemplate.settings,
              updatedAt: new Date().toISOString(),
            }
          : item,
      ),
    );
  }

  function updateActiveResumeTemplateSettings(
    patch: Partial<ResumeTemplateSettings>,
  ) {
    setTemplateSettings((current) => ({
      ...(current ?? activeTemplateDefinition.settings),
      ...patch,
    }));
  }

  function updateActiveResumePageMargin(value: number) {
    updateActiveResumeTemplateSettings({
      pagePaddingTop: value,
      pagePaddingX: value,
      pagePaddingBottom: value,
    });
  }

  async function fitActiveResumeToOnePage() {
    if (!isResumeDetailView || isSmartFittingOnePage) {
      return;
    }

    setIsSmartFittingOnePage(true);

    const previousSnapshot: SmartOnePageStyleSnapshot = {
      typography,
      templateSettings,
    };
    const previousEffectiveSettings = activeResumeTemplateDefinition.settings;

    try {
      await waitForPreviewPagination();

      if (
        getPreviewPageCount(previewRef.current) <= SMART_ONE_PAGE_MAX_PAGE_COUNT
      ) {
        toast.info(t.smartOnePageAlready, {
          duration: 1800,
        });
        return;
      }

      const candidates = createSmartOnePageCandidates(
        typography,
        previousEffectiveSettings,
      ).filter(
        (candidate) =>
          !areSmartOnePageSnapshotsEqual(candidate, {
            typography,
            templateSettings: previousEffectiveSettings,
          }),
      );

      for (const candidate of candidates) {
        setTypography(candidate.typography);
        setTemplateSettings(candidate.templateSettings);

        await waitForPreviewPagination();

        if (
          getPreviewPageCount(previewRef.current) <=
          SMART_ONE_PAGE_MAX_PAGE_COUNT
        ) {
          toast.success(t.smartOnePageApplied, {
            duration: 2600,
            action: {
              label: t.undoAction,
              onClick: () => {
                setTypography(previousSnapshot.typography);
                setTemplateSettings(previousSnapshot.templateSettings);
              },
            },
          });
          return;
        }
      }

      setTypography(previousSnapshot.typography);
      setTemplateSettings(previousSnapshot.templateSettings);
      toast.info(t.smartOnePageNoChange, {
        duration: 1800,
      });
    } finally {
      setIsSmartFittingOnePage(false);
    }
  }

  function handleViewChange(view: WorkspaceView) {
    requestWorkspaceLeave(() => {
      preloadWorkspaceView(view);

      runViewTransition(() => {
        setActiveView(view);
        setShowResumeGallery(view === "resume");
        setShowTemplateGallery(view === "templates");
        navigate(getWorkspacePath(view));
      }, "nav-lateral");
    });
  }

  function updateBasic<K extends keyof ResumeBasicInfo>(
    field: K,
    value: ResumeBasicInfo[K],
  ) {
    setResume((current) => ({
      ...current,
      basic: { ...current.basic, [field]: value },
    }));
  }

  function updateCustomField<K extends keyof Omit<CustomField, "id">>(
    id: string,
    field: K,
    value: CustomField[K],
  ) {
    setResume((current) => ({
      ...current,
      basic: {
        ...current.basic,
        customFields: current.basic.customFields.map((item) =>
          item.id === id ? { ...item, [field]: value } : item,
        ),
      },
    }));
  }

  function addCustomField() {
    startTransition(() => {
      setResume((current) => ({
        ...current,
        basic: {
          ...current.basic,
          customFields: [
            ...current.basic.customFields,
            { id: createId("field"), type: "text", label: "", value: "" },
          ],
        },
      }));
    });
  }

  function removeCustomField(id: string) {
    startTransition(() => {
      setResume((current) => ({
        ...current,
        basic: {
          ...current.basic,
          customFields: current.basic.customFields.filter(
            (field) => field.id !== id,
          ),
        },
      }));
    });
  }

  async function handleAvatarUpload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    try {
      const avatarDataUrl = await readAvatarFileAsDataUrl(file);
      setAvatarCropSource(avatarDataUrl);
    } finally {
      event.target.value = "";
    }
  }

  function updateSection(
    sectionId: string,
    patch: Partial<Omit<ResumeSection, "id" | "items">>,
  ) {
    setResume((current) => ({
      ...current,
      sections: current.sections.map((section) =>
        section.id === sectionId ? { ...section, ...patch } : section,
      ),
    }));
  }

  function removeSection(sectionId: string) {
    setResume((current) => ({
      ...current,
      sections: current.sections.filter(
        (section) => section.id !== sectionId,
      ),
    }));
    setCollapsedState((current) => {
      const nextState = { ...current };
      delete nextState[sectionId];
      return nextState;
    });
  }

  function moveSection(sectionId: string, direction: "up" | "down") {
    startTransition(() => {
      setResume((current) => {
        const currentIndex = current.sections.findIndex(
          (section) => section.id === sectionId,
        );

        if (currentIndex < 0) {
          return current;
        }

        const targetIndex =
          direction === "up" ? currentIndex - 1 : currentIndex + 1;

        if (targetIndex < 0 || targetIndex >= current.sections.length) {
          return current;
        }

        const nextSections = [...current.sections];
        const [targetSection] = nextSections.splice(currentIndex, 1);
        nextSections.splice(targetIndex, 0, targetSection);

        return {
          ...current,
          sections: nextSections,
        };
      });
    });
  }

  function addResumeSection(kind: SectionKind = "custom") {
    const nextSection = ["skills", "certificates", "languages", "other"].includes(kind)
      ? createSection(kind, "list", [createItem()])
      : createSection(kind, "timeline", [createItem()]);

    startTransition(() => {
      setResume((current) => ({
        ...current,
        sections: [...current.sections, nextSection],
      }));
    });

    setCollapsedState((current) => collapseAllExcept(current, nextSection.id));
  }

  function updateSectionItem(
    sectionId: string,
    itemId: string,
    field: keyof Omit<ResumeSectionItem, "id" | "highlights">,
    value: string,
  ) {
    setResume((current) => ({
      ...current,
      sections: current.sections.map((section) =>
        section.id === sectionId
          ? {
              ...section,
              items: section.items.map((item) =>
                item.id === itemId ? { ...item, [field]: value } : item,
              ),
            }
          : section,
      ),
    }));
  }

  function updateSectionHighlights(
    sectionId: string,
    itemId: string,
    value: string,
  ) {
    setResume((current) => ({
      ...current,
      sections: current.sections.map((section) =>
        section.id === sectionId
          ? {
              ...section,
              items: section.items.map((item) =>
                item.id === itemId
                  ? {
                      ...item,
                      highlights: isRichTextEmpty(value) ? [] : [value],
                    }
                  : item,
              ),
            }
          : section,
      ),
    }));
  }

  function addSectionItem(sectionId: string) {
    startTransition(() => {
      setResume((current) => ({
        ...current,
        sections: current.sections.map((section) =>
          section.id === sectionId
            ? { ...section, items: [...section.items, createItem()] }
            : section,
        ),
      }));
    });
  }

  function removeSectionItem(sectionId: string, itemId: string) {
    startTransition(() => {
      setResume((current) => ({
        ...current,
        sections: current.sections.map((section) =>
          section.id === sectionId
            ? {
                ...section,
                items: section.items.filter((item) => item.id !== itemId),
              }
            : section,
        ),
      }));
    });
  }

  function toggleCollapse(id: string) {
    setCollapsedState((current) => {
      if (current[id] === false) {
        return { ...current, [id]: true };
      }

      return collapseAllExcept(current, id);
    });
  }

  function buildPdfExportUrl(input: {
    resumeId: string;
    savedAt: string;
    versionId?: string;
    shouldPrint?: boolean;
  }) {
    const url = new URL("/pdf-export", window.location.origin);

    url.searchParams.set("resumeId", input.resumeId);
    url.searchParams.set("locale", locale);
    url.searchParams.set("savedAt", input.savedAt);
    if (input.shouldPrint) {
      url.searchParams.set("print", "1");
    }
    if (input.versionId) {
      url.searchParams.set("versionId", input.versionId);
    }

    return url.toString();
  }

  function createPdfExportFrame(title: string) {
    const frame = document.createElement("iframe");
    let cleanupTimer: number | undefined;

    function cleanup() {
      if (cleanupTimer !== undefined) {
        window.clearTimeout(cleanupTimer);
        cleanupTimer = undefined;
      }
      frame.remove();
    }

    frame.title = title;
    frame.setAttribute("aria-hidden", "true");
    frame.style.position = "fixed";
    frame.style.right = "0";
    frame.style.bottom = "0";
    frame.style.width = "0";
    frame.style.height = "0";
    frame.style.border = "0";
    frame.style.opacity = "0";
    frame.style.pointerEvents = "none";

    frame.addEventListener(
      "load",
      () => {
        frame.contentWindow?.addEventListener("afterprint", cleanup, {
          once: true,
        });
      },
      { once: true },
    );

    document.body.append(frame);

    return {
      cleanup,
      load(source: string) {
        frame.src = source;
        cleanupTimer = window.setTimeout(cleanup, 120_000);
      },
    };
  }

  async function exportPdf() {
    if (exportInFlightRef.current || !activeResumeId) {
      return;
    }

    exportInFlightRef.current = true;
    setIsExporting(true);
    const exportFrame = createPdfExportFrame(t.exportPdf);

    try {
      const savedVersion = await saveCurrentWorkspace();
      const exportUrl = buildPdfExportUrl({
        resumeId: activeResumeId,
        savedAt: savedVersion.savedAt,
        versionId: savedVersion.versionId ?? undefined,
        shouldPrint: true,
      });

      exportFrame.load(exportUrl);
      toast.success(t.exportSuccess, {
        closeButton: true,
      });
    } catch (error) {
      exportFrame.cleanup();
      console.error("Failed to export resume PDF.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.exportFailed, {
          closeButton: true,
        });
      }
    } finally {
      exportInFlightRef.current = false;
      setIsExporting(false);
    }
  }

  async function exportImages() {
    if (exportInFlightRef.current || !activeResumeId) {
      return;
    }

    exportInFlightRef.current = true;
    setIsExporting(true);

    try {
      const savedVersion = await saveCurrentWorkspace();
      const activeResume = buildActiveResumeItem(savedVersion.savedAt);
      if (!activeResume) {
        throw new Error("No active resume is available for image export.");
      }

      const result = await requestResumeImagesExport({
        resumeId: activeResume.id,
        locale,
        fileNameSeed: activeResume.title,
        savedAt: savedVersion.savedAt,
        versionId: savedVersion.versionId,
      });
      await downloadExportedFile(result);
      toast.success(t.exportImagesSuccess, {
        closeButton: true,
      });
    } catch (error) {
      console.error("Failed to export resume images.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.exportImagesFailed, {
          closeButton: true,
        });
      }
    } finally {
      exportInFlightRef.current = false;
      setIsExporting(false);
    }
  }

  async function exportJson() {
    if (exportInFlightRef.current || !activeResumeId) {
      return;
    }

    exportInFlightRef.current = true;
    setIsExporting(true);

    try {
      const savedVersion = await saveCurrentWorkspace();
      const activeResume = buildActiveResumeItem(savedVersion.savedAt);
      if (!activeResume) {
        throw new Error("No active resume is available for JSON export.");
      }

      downloadResumeJson(activeResume);
      toast.success(t.exportJsonSuccess, {
        closeButton: true,
      });
    } catch (error) {
      console.error("Failed to export resume JSON.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.exportJsonFailed, {
          closeButton: true,
        });
      }
    } finally {
      exportInFlightRef.current = false;
      setIsExporting(false);
    }
  }

  function renderPreviewCard() {
    const scaledPreviewWidth = A4_WIDTH_PX * previewScale;
    const scaledPreviewHeight = previewPageHeight * previewScale;
    const previewTransitionName =
      activeView === "templates"
        ? `template-preview-${template}`
        : activeResumeId
          ? `resume-preview-${activeResumeId}`
          : undefined;

    return (
      <section
        className="resume-preview-card relative flex min-w-0 flex-col overflow-x-hidden rounded-(--radius-preview) border border-border bg-card p-4 print:overflow-visible print:border-0 print:bg-white print:p-0 xl:self-start"
      >
        <div className="mb-4 print:hidden">
          <p className="text-xs font-medium text-muted-foreground">
            {t.previewTitle}
          </p>
        </div>
        <ViewTransitionBoundary
          name={previewTransitionName}
          share="morph"
          default="none"
        >
          <div
            ref={previewScaleFrameRef}
            className="resume-preview-scale-frame flex min-w-0 justify-center overflow-hidden print:block print:overflow-visible"
          >
            <div
              className="resume-preview-scale-box relative print:contents"
              style={{
                width: scaledPreviewWidth,
                height: scaledPreviewHeight,
              }}
            >
              <div
                className="resume-preview-scale-content origin-top-left print:contents"
                style={{
                  width: "210mm",
                  transform: `scale(${previewScale})`,
                }}
              >
                <ResumePreview
                  ref={previewRef}
                  t={t}
                  resume={previewDocument}
                  fontFamily={
                    activeView === "templates"
                      ? activeTemplateDefinition.typography.fontFamily
                      : typography.fontFamily
                  }
                  fontSize={
                    activeView === "templates"
                      ? activeTemplateDefinition.typography.fontSize
                      : typography.fontSize
                  }
                  template={
                    activeView === "templates"
                      ? activeTemplateDefinition
                      : activeResumeTemplateDefinition
                  }
                  diffs={activeView === "resume" ? agentDraft?.diffs : undefined}
                  editableTemplateImages={
                    activeView === "templates" &&
                    !activeTemplateDefinition.isBuiltIn
                  }
                  onMoveTemplateImage={moveTemplateImage}
                />
              </div>
            </div>
          </div>
        </ViewTransitionBoundary>

      </section>
    );
  }

  function renderAgentSeamRail() {
    if (!isAgentDockLayout) {
      return null;
    }

    const tooltip = isAgentPanelCollapsed
      ? t.agentExpandPanel
      : t.agentCollapsePanel;
    const RailIcon = isAgentPanelCollapsed
      ? ChevronLeft
      : ChevronRight;

    return (
      <div
        className={cn(
          "agent-seam-rail hidden print:hidden 2xl:flex",
          isAgentPanelCollapsed && "agent-seam-rail--collapsed",
        )}
      >
        <TooltipProvider delayDuration={180}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={tooltip}
                className="agent-seam-rail-button"
                onClick={() =>
                  setIsAgentPanelCollapsed((current) => !current)
                }
              >
                <span className="agent-seam-rail-track" aria-hidden="true">
                  <RailIcon className="agent-seam-rail-icon" />
                </span>
              </Button>
            </TooltipTrigger>
            <TooltipContent side="left">{tooltip}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    );
  }

  function renderResumeGalleryWorkspace() {
    const skeletonItemCount = Math.max(1, resumeDocuments.length);

    if (isLoading) {
      return <GalleryRouteSkeleton itemCount={skeletonItemCount} />;
    }

    return (
      <main className="flex-1 p-4">
        <Suspense
          fallback={
            <GalleryWorkspaceSkeleton itemCount={skeletonItemCount} />
          }
        >
          <ResumeGallery
            locale={locale}
            t={t}
            resumes={resumeDocuments}
            templates={templateCatalog}
            defaultTemplateId={defaultTemplateId}
            isImporting={isImporting}
            isCreating={isCreatingResume}
            onOpenResume={openResumeEditor}
            onCreateResume={createResume}
            onImportResume={(file) => {
              void importResume(file);
            }}
            onDeleteResume={(resumeId) => moveResumesToTrash([resumeId])}
            onBulkDeleteResumes={moveResumesToTrash}
          />
        </Suspense>
      </main>
    );
  }

  function renderTemplateGalleryWorkspace() {
    const skeletonItemCount = Math.max(1, templateCatalog.length);

    if (isLoading) {
      return <GalleryRouteSkeleton itemCount={skeletonItemCount} />;
    }

    return (
      <main className="flex-1 p-4">
        <Suspense
          fallback={<GalleryWorkspaceSkeleton itemCount={skeletonItemCount} />}
        >
          <TemplateLibrary
            mode="gallery"
            t={t}
            resume={deferredTemplatePreviewResume}
            templates={templateCatalog}
            defaultTemplateId={defaultTemplateId}
            activeTemplateId={template}
            isImporting={isImporting}
            isCreating={isCreatingTemplate}
            settingDefaultTemplateId={settingDefaultTemplateId}
            onOpenTemplate={openTemplateEditor}
            onSetDefaultTemplate={handleSetDefaultTemplate}
            onCreateCustomTemplate={createCustomTemplate}
            onImportTemplates={(file) => {
              void importTemplates(file);
            }}
            onUpdateTemplate={updateCustomTemplate}
            onDeleteTemplate={(templateId) => deleteTemplates([templateId])}
            onBulkDeleteTemplates={deleteTemplates}
          />
        </Suspense>
      </main>
    );
  }

  function renderTrashWorkspace() {
    if (isLoading) {
      return <WorkspaceRouteSkeleton />;
    }

    return (
      <Suspense fallback={<WorkspaceContentSkeleton />}>
        <RecycleBinPanel
          locale={locale}
          t={t}
          deletedResumes={deletedResumeDocuments}
          deletedTemplates={deletedTemplates}
          templates={templateCatalog}
          defaultTemplateId={defaultTemplateId}
          templatePreviewResume={deferredTemplatePreviewResume}
          onRestoreResume={restoreResumes}
          onDeleteResumeForever={permanentlyDeleteResumes}
          onRestoreTemplate={restoreTemplates}
          onDeleteTemplateForever={permanentlyDeleteTemplates}
        />
      </Suspense>
    );
  }

  function renderResumeWorkspace() {
    const shouldDockAgent = isAgentDockLayout && !isAgentPanelCollapsed;
    const resumeWorkspaceStyle = {
      "--resume-workspace-columns": shouldDockAgent
        ? "440px minmax(0,1fr) 18px 360px"
        : "440px minmax(0,1fr) 18px 0px",
    } as CSSProperties;
    const renderCopilotPanel = (mode: "docked" | "sheet") => (
      <Suspense
        fallback={
          <Card className="h-full min-h-0 rounded-[32px] border-border/60">
            <CardContent className="space-y-5 p-4">
              <div className="flex items-center gap-3">
                <Skeleton className="size-11 rounded-2xl" />
                <Skeleton className="h-5 w-28" />
              </div>
              <Skeleton className="h-36 rounded-3xl" />
              <Skeleton className="h-48 rounded-3xl" />
              <Skeleton className="mt-auto h-44 rounded-[26px]" />
            </CardContent>
          </Card>
        }
      >
        <CopilotPanel
          key={`${activeResumeId ?? "resume"}-${mode}`}
          mode={mode}
          resumeId={activeResumeId ?? undefined}
          t={t}
          locale={locale}
          resume={resume}
          jobBrief={jobBrief}
          onJobBriefChange={setJobBrief}
          keywordMatch={keywordMatch}
          modelConfigs={modelConfigs}
          selectedModelId={agentSettings.defaultModelId}
          onSelectedModelChange={(modelId) =>
            handleAgentSettingsChange({
              ...agentSettings,
              defaultModelId: modelId,
            })
          }
          hasAgentDraft={Boolean(agentDraft)}
          agentDraftState={agentDraftState}
          onPreviewAgentEdits={previewAgentEdits}
          onRollbackAgentDraft={rollbackAgentDraft}
          onApplyAgentDraft={applyAgentDraft}
          onDiscardAgentDraft={discardAgentDraft}
          onOpenModelSettings={() => handleViewChange("models")}
          onBeforeSend={flushUserSettings}
        />
      </Suspense>
    );

    return (
      <main
        style={resumeWorkspaceStyle}
        className={cn(
          "resume-workspace relative grid min-w-0 flex-1 gap-y-4 gap-x-3 p-4 xl:gap-x-2",
          "print:block print:h-auto print:overflow-visible print:p-0",
        )}
      >
        <section
          className="resume-editor-panel flex flex-col gap-4 print:hidden"
        >
          {hasLoadError ? (
            <Card className="rounded-2xl border-border/80 shadow-sm">
              <CardContent className="p-5 text-sm text-muted-foreground">
                {t.loadError}
              </CardContent>
            </Card>
          ) : null}

          {isLoading ? (
            <WorkspacePanelSkeleton />
          ) : (
            <>
              <BasicInfoCard
                t={t}
                basic={resume.basic}
                collapsed={Boolean(collapsedState.basic)}
                onToggle={() => toggleCollapse("basic")}
                onUpdateBasic={updateBasic}
                onUpdateCustomField={updateCustomField}
                onAddCustomField={addCustomField}
                onRemoveCustomField={removeCustomField}
                onAvatarUpload={handleAvatarUpload}
                onRemoveAvatar={() => updateBasic("avatar", "")}
              />

              {resume.sections.map((section) => (
                <ResumeSectionCard
                  key={section.id}
                  t={t}
                  section={section}
                  canMoveUp={resume.sections[0]?.id !== section.id}
                  canMoveDown={
                    resume.sections[resume.sections.length - 1]?.id !== section.id
                  }
                  collapsed={Boolean(collapsedState[section.id])}
                  onToggle={() => toggleCollapse(section.id)}
                  onUpdateSection={updateSection}
                  onAddItem={addSectionItem}
                  onRemoveSection={removeSection}
                  onMoveSectionUp={(sectionId) => moveSection(sectionId, "up")}
                  onMoveSectionDown={(sectionId) => moveSection(sectionId, "down")}
                  onUpdateItem={updateSectionItem}
                  onUpdateHighlights={updateSectionHighlights}
                  onRemoveItem={removeSectionItem}
                />
              ))}

              <Button
                type="button"
                variant="outline"
                className="h-11 rounded-2xl border-dashed bg-background/95"
                onClick={() => addResumeSection("custom")}
              >
                <Plus className="size-4" />
                {t.addSection}
              </Button>
            </>
          )}
        </section>

        {isLoading ? <WorkspacePreviewSkeleton /> : renderPreviewCard()}

        {renderAgentSeamRail()}

        {isAgentDockLayout ? (
          <aside
            aria-hidden={!shouldDockAgent}
            className={cn(
              "agent-panel-dock relative min-w-0 self-start overflow-hidden print:hidden",
              "transition-opacity duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]",
              !shouldDockAgent && "pointer-events-none opacity-0",
            )}
          >
            {renderCopilotPanel("docked")}
          </aside>
        ) : null}

        {!isAgentDockLayout ? (
          <Sheet open={isAgentSheetOpen} onOpenChange={setIsAgentSheetOpen}>
            <SheetContent
              closeLabel={t.close}
              side="right"
              className="w-[420px] max-w-[calc(100vw-1rem)] p-2 sm:max-w-[420px]"
            >
              <SheetHeader className="sr-only">
                <SheetTitle>{t.aiTitle}</SheetTitle>
                <SheetDescription>{t.agentEmptyPrompt}</SheetDescription>
              </SheetHeader>
              {renderCopilotPanel("sheet")}
            </SheetContent>
          </Sheet>
        ) : null}
      </main>
    );
  }

  function renderTemplatesWorkspace() {
    return (
      <main
        className={cn(
          "template-workspace grid min-w-0 flex-1 gap-4 p-4 xl:grid-cols-[460px_minmax(0,1fr)]",
        )}
      >
        <section
          className="resume-editor-panel resume-template-editor-panel flex flex-col gap-4 print:hidden"
        >
          {hasLoadError ? (
            <Card className="rounded-2xl border-border/80 shadow-sm">
              <CardContent className="p-5 text-sm text-muted-foreground">
                {t.loadError}
              </CardContent>
            </Card>
          ) : null}

          <Suspense fallback={<WorkspacePanelSkeleton />}>
            <TemplateLibrary
              mode="editor"
              t={t}
              resume={deferredTemplatePreviewResume}
              templates={templateCatalog}
              defaultTemplateId={defaultTemplateId}
              activeTemplateId={template}
              isImporting={isImporting}
              isCreating={isCreatingTemplate}
              settingDefaultTemplateId={settingDefaultTemplateId}
              onOpenTemplate={openTemplateEditor}
              onSetDefaultTemplate={handleSetDefaultTemplate}
              onCreateCustomTemplate={createCustomTemplate}
              onImportTemplates={(file) => {
                void importTemplates(file);
              }}
              onUpdateTemplate={updateCustomTemplate}
              onDeleteTemplate={(templateId) => deleteTemplates([templateId])}
              onBulkDeleteTemplates={deleteTemplates}
            />
          </Suspense>
        </section>

        {isLoading ? <WorkspacePreviewSkeleton /> : renderPreviewCard()}
      </main>
    );
  }

  function renderModelsWorkspace() {
    if (isLoading) {
      return <WorkspaceRouteSkeleton />;
    }

    return (
      <main className="flex-1 p-4">
        <Suspense fallback={<WorkspaceContentSkeleton />}>
          <ModelConfigPanel
            locale={locale}
            t={t}
            configs={modelConfigs}
            onChange={handleModelConfigsChange}
          />
        </Suspense>
      </main>
    );
  }

  function renderSettingsWorkspace() {
    if (isLoading) {
      return <WorkspaceRouteSkeleton />;
    }

    return (
      <Suspense fallback={<WorkspaceRouteSkeleton />}>
        <SettingsPanel
          locale={locale}
          t={t}
          theme={theme}
          onThemeChange={handleSettingsThemeChange}
          onLocaleChange={handleSettingsLocaleChange}
          agentSettings={agentSettings}
          onAgentSettingsChange={handleAgentSettingsChange}
          modelConfigs={modelConfigs}
          onPasswordChanged={onLogout}
        />
      </Suspense>
    );
  }

  return (
    <SidebarProvider>
      <a
        href="#main-content"
        className="fixed left-4 top-4 z-50 -translate-y-20 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground shadow-md transition-transform focus-visible:translate-y-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 print:hidden"
      >
        {t.skipToContent}
      </a>
      <AppToaster theme={theme} position="bottom-right" />
      <AvatarCropDialog
        t={t}
        open={Boolean(avatarCropSource)}
        source={avatarCropSource}
        onCancel={() => setAvatarCropSource(null)}
        onConfirm={(value) => {
          updateBasic("avatar", value);
          setAvatarCropSource(null);
        }}
      />
      <Dialog
        open={isResumeTitleDialogOpen}
        onOpenChange={(open) => {
          setIsResumeTitleDialogOpen(open);

          if (open) {
            setResumeTitleDraft(activeResumeTitle || t.untitledResume);
          }
        }}
      >
        <DialogContent
          showCloseButton
          closeLabel={t.close}
          className="w-[min(420px,calc(100vw-2rem))]"
        >
          <DialogHeader>
            <DialogTitle>{t.editResumeTitle}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-2">
            <label
              htmlFor="resume-title-input"
              className="text-sm font-medium text-foreground"
            >
              {t.resumeTitle}
            </label>
            <Input
              id="resume-title-input"
              value={resumeTitleDraft}
              maxLength={MAX_RESUME_TITLE_LENGTH}
              autoFocus
              onChange={(event) =>
                setResumeTitleDraft(
                  normalizeResumeTitle(event.target.value, ""),
                )
              }
            />
            <p className="text-right text-xs text-muted-foreground">
              {Array.from(resumeTitleDraft).length}/{MAX_RESUME_TITLE_LENGTH}
            </p>
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline" className="h-10 min-w-[72px] rounded-lg px-4">
                {t.cancel}
              </Button>
            </DialogClose>
            <Button
              type="button"
              variant="ghost"
              className="h-10 min-w-[72px] rounded-lg px-4 font-semibold hover:opacity-90"
              style={{
                backgroundColor: "var(--foreground)",
                color: "var(--background)",
              }}
              onClick={saveActiveResumeTitle}
            >
              {resumeTitleSaveLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(pendingWorkspaceLeaveAction)}
        onOpenChange={(open) => {
          if (!open && !isResolvingWorkspaceLeave) {
            setPendingWorkspaceLeaveAction(null);
          }
        }}
      >
        <DialogContent
          showCloseButton
          closeLabel={t.close}
          className="w-[min(460px,calc(100vw-2rem))]"
          onKeyDown={(event) => {
            if (event.key !== "Enter" || isResolvingWorkspaceLeave) {
              return;
            }

            event.preventDefault();
            void saveAndRunPendingWorkspaceLeaveAction();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t.unsavedChangesTitle}</DialogTitle>
            <DialogDescription>
              {t.unsavedChangesDescription.replace(
                "{count}",
                String(Math.max(1, unsavedWorkspaceChangeCount)),
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:justify-end">
            <Button
              type="button"
              variant="outline"
              disabled={isResolvingWorkspaceLeave}
              onClick={() => setPendingWorkspaceLeaveAction(null)}
            >
              {t.unsavedChangesContinueEditing}
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={isResolvingWorkspaceLeave}
              onClick={discardAndRunPendingWorkspaceLeaveAction}
            >
              {t.unsavedChangesDiscard}
            </Button>
            <Button
              type="button"
              disabled={isResolvingWorkspaceLeave}
              onClick={() => void saveAndRunPendingWorkspaceLeaveAction()}
            >
              {isResolvingWorkspaceLeave
                ? t.saving
                : t.unsavedChangesSaveAndLeave}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AppSidebar
        t={t}
        activeView={activeView}
        onViewChange={handleViewChange}
        onViewPreload={preloadWorkspaceView}
      />

      <SidebarInset
        id="main-content"
        tabIndex={-1}
        className={cn(
          "app-shell",
          (isResumeDetailView || isTemplateDetailView) &&
            "app-shell--document",
        )}
        style={
          isResumeDetailView || isTemplateDetailView
            ? ({
                "--document-sticky-top": `${documentStickyTop}px`,
              } as CSSProperties)
            : undefined
        }
      >
        <header
          ref={documentHeaderRef}
          className={cn(
            "sticky top-0 z-20 items-center gap-3 border-b border-border bg-background px-4 print:hidden",
            isResumeDetailView
              ? "grid min-h-16 grid-cols-[auto_minmax(0,1fr)] py-2"
              : isTemplateDetailView
                ? "flex min-h-16 flex-wrap justify-between py-2"
                : "flex h-16 shrink-0 justify-between",
          )}
          style={{ viewTransitionName: "persistent-header" }}
        >
          <div className="flex min-w-0 items-center gap-2">
            <SidebarTrigger
              className="-ml-1"
              aria-label={t.toggleSidebar}
              title={t.toggleSidebar}
            />
            {!isResumeDetailView && !isTemplateDetailView ? (
              <Separator
                orientation="vertical"
                className="mr-2 data-[orientation=vertical]:h-4"
              />
            ) : null}
            {isResumeDetailView || isTemplateDetailView ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  if (isResumeDetailView) {
                    requestWorkspaceLeave(() =>
                      runViewTransition(() => navigate("/resume"), "nav-back"),
                    );
                    return;
                  }

                  runViewTransition(() => navigate("/templates"), "nav-back");
                }}
              >
                <ChevronLeft className="size-4" />
                {isResumeDetailView ? t.backToResumes : t.backToTemplates}
              </Button>
            ) : null}
            {isResumeDetailView ? (
              <div className="flex min-w-0 items-center gap-1">
                <h1
                  className="max-w-36 truncate text-sm font-medium text-foreground"
                  title={activeResumeToolbarTitle}
                >
                  {formatResumeTitleForToolbar(activeResumeToolbarTitle)}
                </h1>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t.editResumeTitle}
                  onClick={openResumeTitleDialog}
                >
                  <Pencil className="size-3.5 text-muted-foreground" />
                </Button>
              </div>
            ) : null}
            {isTemplateDetailView ? (
              <h1 className="max-w-48 truncate text-sm font-medium text-foreground">
                {activeTemplateDefinition.name}
              </h1>
            ) : null}
            {!isResumeDetailView && !isTemplateDetailView ? (
              <h1 className="text-sm font-medium text-foreground">
                {pageEyebrow}
              </h1>
            ) : null}
          </div>

          <div
            className={cn(
              isResumeDetailView
                ? "flex min-w-0 flex-wrap items-center justify-end gap-2"
                : "flex flex-wrap items-center justify-end gap-2",
            )}
          >
            {showEditorControls || canSaveCurrentWorkspace ? (
              <div className="flex flex-wrap items-center justify-end gap-2">
            {showEditorControls && isResumeDetailView && !isAgentDockLayout ? (
              <Button
                type="button"
                variant="outline"
                aria-label={t.agentExpandPanel}
                onFocus={() => void loadCopilotPanelModule()}
                onPointerEnter={() => void loadCopilotPanelModule()}
                onClick={() => setIsAgentSheetOpen(true)}
              >
                <Bot data-icon="inline-start" />
                {t.aiTitle}
              </Button>
            ) : null}

            {showEditorControls && isResumeDetailView ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => void fitActiveResumeToOnePage()}
                disabled={isSmartFittingOnePage}
                title={t.smartOnePage}
                aria-label={t.smartOnePage}
              >
                {isSmartFittingOnePage ? (
                  <Spinner data-icon="inline-start" aria-label={t.smartOnePage} />
                ) : (
                  <Minimize2 data-icon="inline-start" />
                )}
                {t.smartOnePage}
              </Button>
            ) : null}

            {showEditorControls && isResumeDetailView ? (
              <Popover>
                <PopoverTrigger
                  type="button"
                  className={cn(buttonVariants({ variant: "outline" }))}
                >
                  <SlidersHorizontal className="size-4" />
                  {t.format}
                </PopoverTrigger>
                <PopoverContent align="end" className="w-[340px] p-3">
                  <div className="grid gap-2.5">
                    <div className="flex min-h-8 items-center justify-between gap-3">
                      <span className="text-sm font-medium text-foreground">
                        {t.template}
                      </span>
                      <Select
                        value={template}
                        onValueChange={applyTemplateToActiveResume}
                      >
                        <SelectTrigger
                          aria-label={t.applyTemplate}
                          className="h-8 w-[148px] justify-end rounded-md border-0 bg-transparent px-1.5 text-sm font-medium text-foreground shadow-none hover:bg-muted/60 focus-visible:border-transparent"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent
                          align="end"
                          position="popper"
                          sideOffset={6}
                        >
                          <SelectGroup>
                            {templateCatalog.map((item) => (
                              <SelectItem key={item.id} value={item.id}>
                                {item.name}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        </SelectContent>
                      </Select>
                    </div>

                    <Separator />

                    <div className="px-0.5 text-sm font-semibold">
                      {t.formatTypography}
                    </div>

                    <div className="grid gap-1">
                      <div className="flex min-h-8 items-center justify-between gap-3">
                        <span className="text-sm font-medium text-foreground">
                          {t.fontFamily}
                        </span>
                        <Select
                          value={typography.fontFamily}
                          onValueChange={(value) =>
                            setTypography((current) => ({
                              ...current,
                              fontFamily: value as ResumeFontFamily,
                            }))
                          }
                        >
                          <SelectTrigger
                            aria-label={t.fontFamily}
                            className="h-8 w-[104px] justify-end rounded-md border-0 bg-transparent px-1.5 text-sm font-medium text-foreground shadow-none hover:bg-muted/60 focus-visible:border-transparent"
                          >
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {Object.entries(fontLabels).map(
                              ([value, labelKey]) => (
                                <SelectItem key={value} value={value}>
                                  {t[labelKey]}
                                </SelectItem>
                              ),
                            )}
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="flex min-h-8 items-center justify-between gap-3">
                        <span className="text-sm font-medium text-foreground">
                          {t.fontSize}
                        </span>
                        <Select
                          value={String(typography.fontSize)}
                          onValueChange={(value) =>
                            setTypography((current) => ({
                              ...current,
                              fontSize: Number(value),
                            }))
                          }
                        >
                          <SelectTrigger
                            aria-label={t.fontSize}
                            className="h-8 w-[104px] justify-end rounded-md border-0 bg-transparent px-1.5 text-sm font-medium text-foreground shadow-none hover:bg-muted/60 focus-visible:border-transparent"
                          >
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {resumeFontSizeOptions.map((size) => (
                              <SelectItem key={size} value={String(size)}>
                                {getResumeFontSizeInPoints(size)} pt
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>

                    <Separator />

                    <FormatSliderField
                      label={t.pageMargin}
                      value={
                        activeResumeTemplateDefinition.settings.pagePaddingX
                      }
                      min={8}
                      max={18}
                      step={1}
                      suffix="mm"
                      onChange={updateActiveResumePageMargin}
                    />
                    <FormatSliderField
                      label={t.lineSpacing}
                      value={
                        activeResumeTemplateDefinition.settings.bodyLineHeight
                      }
                      min={1.4}
                      max={2.2}
                      step={0.05}
                      onChange={(value) =>
                        updateActiveResumeTemplateSettings({
                          bodyLineHeight: value,
                        })
                      }
                    />
                  </div>
                </PopoverContent>
              </Popover>
            ) : null}

            {isResumeDetailView ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => void duplicateActiveResume()}
                disabled={
                  isDuplicatingResume || isLoading || saveState === "saving"
                }
              >
                {isDuplicatingResume ? (
                  <Spinner data-icon="inline-start" />
                ) : (
                  <CopyPlus data-icon="inline-start" />
                )}
                {t.duplicateResume}
              </Button>
            ) : null}

            {canSaveCurrentWorkspace ? (
              <SaveStatusButton
                locale={locale}
                label={t.saveStatus}
                savingText={t.saving}
                savedText={t.saved}
                unsavedText={t.unsaved}
                lastSavedLabel={t.lastSavedAt}
                state={saveState}
                hasUnsavedChanges={unsavedWorkspaceChangeCount > 0}
                lastSavedAt={lastSavedAt}
                versions={workspaceVersions}
                activeVersionId={activeWorkspaceVersionId}
                versionsLabel={t.saveVersions}
                currentVersionLabel={t.currentVersion}
                noVersionsText={t.noSaveVersions}
                onSave={() => void saveCurrentWorkspace()}
                onSelectVersion={(versionId) =>
                  requestWorkspaceLeave(() => void selectWorkspaceVersion(versionId))
                }
                showVersions={isResumeDetailView}
              />
            ) : null}

            {showEditorControls ? (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    disabled={isExporting || isLoading}
                  >
                    {isExporting ? (
                      <Spinner
                        data-icon="inline-start"
                        aria-label={t.exporting}
                      />
                    ) : (
                      <Download data-icon="inline-start" />
                    )}
                    {isExporting ? t.exporting : t.export}
                    {!isExporting ? (
                      <ChevronDown
                        data-icon="inline-end"
                        className="opacity-50"
                      />
                    ) : null}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuGroup>
                    <DropdownMenuItem onSelect={() => void exportPdf()}>
                      <FileText />
                      {t.exportPdf}
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => void exportImages()}>
                      <Images />
                      {t.exportImages}
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => void exportJson()}>
                      <FileJson />
                      {t.exportJson}
                    </DropdownMenuItem>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
            ) : null}
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-end gap-2">
              <Select
                value={locale}
                onValueChange={(value) => {
                  if (value === "zh" || value === "en") {
                    onLocaleChange(value);
                  }
                }}
              >
                <SelectTrigger
                  className="w-28 bg-background font-medium transition-all hover:bg-accent hover:text-accent-foreground"
                  aria-label={t.language}
                >
                  <Languages className="text-foreground" aria-hidden="true" />
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end" position="popper" sideOffset={4}>
                  <SelectGroup>
                    <SelectItem value="zh">{t.languageChinese}</SelectItem>
                    <SelectItem value="en">{t.languageEnglish}</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
              <Button
                type="button"
                variant="outline"
                size="icon"
                title={t.themeToggleLabel}
                aria-label={t.themeToggleLabel}
                onClick={() =>
                  handleSettingsThemeChange(
                    resolvedTheme === "dark" ? "light" : "dark",
                  )
                }
              >
                {resolvedTheme === "dark" ? (
                  <Sun className="size-4" />
                ) : (
                  <Moon className="size-4" />
                )}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => requestWorkspaceLeave(onLogout)}
              >
                <LogOut className="size-4" />
                {t.logout}
              </Button>
            </div>
          </div>
        </header>

        <ViewTransitionBoundary
          default="none"
          enter={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            "nav-lateral": "fade-in",
            default: "none",
          }}
          exit={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            "nav-lateral": "fade-out",
            default: "none",
          }}
          update={{
            "nav-forward": "nav-forward",
            "nav-back": "nav-back",
            "nav-lateral": "fade-in",
            default: "none",
          }}
        >
          {activeView === "resume"
            ? showResumeGallery
              ? renderResumeGalleryWorkspace()
              : renderResumeWorkspace()
            : activeView === "templates"
              ? showTemplateGallery
                ? renderTemplateGalleryWorkspace()
                : renderTemplatesWorkspace()
              : activeView === "trash"
                ? renderTrashWorkspace()
                : activeView === "models"
                  ? renderModelsWorkspace()
                  : renderSettingsWorkspace()}
        </ViewTransitionBoundary>
      </SidebarInset>
    </SidebarProvider>
  );
}
