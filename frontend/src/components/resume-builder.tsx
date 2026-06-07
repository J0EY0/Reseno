import {
  ALargeSmall,
  ChevronLeft,
  ChevronRight,
  Download,
  Languages,
  LayoutTemplate,
  LogOut,
  Moon,
  Pencil,
  Plus,
  SlidersHorizontal,
  Sun,
  Type,
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
  type ReactNode,
} from "react";
import { matchPath, useLocation, useNavigate } from "react-router-dom";

import { AppSidebar } from "@/components/app-sidebar";
import { AvatarCropDialog } from "@/components/editor/avatar-crop-dialog";
import { BasicInfoCard } from "@/components/editor/basic-info-card";
import { ResumeSectionCard } from "@/components/editor/resume-section-card";
import { ResumePreview } from "@/components/preview/resume-preview";
import { SaveStatusButton } from "@/components/save-status-button";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Toaster } from "@/components/ui/sonner";
import { Skeleton } from "@/components/ui/skeleton";
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
import { ViewTransitionBoundary } from "@/components/ui/view-transition";
import { readAvatarFileAsDataUrl } from "@/lib/avatar";
import {
  createDefaultAgentSettings,
  normalizeAgentSettings,
} from "@/lib/agent-settings";
import { isApiErrorToastShown } from "@/lib/api-client";
import { applyAgentEditsToDraft } from "@/lib/resume-agent-edits";
import {
  downloadExportedPdf,
  requestResumePdfExport,
} from "@/lib/export-api";
import {
  importResumePayload,
  importTemplatePayload,
} from "@/lib/import-api";
import { normalizeModelConfigs } from "@/lib/model-config";
import { isRichTextEmpty } from "@/lib/rich-text";
import {
  createTemplateSettings,
  createTemplateLayout,
  createCustomTemplateFromBase,
  getTemplateById,
  getTemplateCatalog,
  normalizeCustomTemplates,
  normalizeDeletedTemplates,
} from "@/lib/templates";
import { type AppMessages, type Locale } from "@/i18n";
import {
  createEmptyResume,
  createId,
  createItem,
  createSection,
  getKeywordMatch,
} from "@/lib/resume";
import { cn } from "@/lib/utils";
import {
  fetchWorkspaceBootstrap,
  fetchWorkspaceVersion,
  fetchWorkspaceVersions,
  saveWorkspaceSnapshotApi,
} from "@/lib/workspace-api";
import { runViewTransition } from "@/lib/view-transition";
import type {
  AgentResumeEditSuggestion,
  WorkspaceSaveResponse,
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
  ResumeDraftDiff,
  ResumeFontFamily,
  ResumeSection,
  ResumeSectionItem,
  ResumeTemplateDefinition,
  ResumeTemplateId,
  ResumeTemplateImageElement,
  ResumeTemplateSettings,
  ResumeTypographySettings,
  ResumeWorkspaceItem,
  WorkspaceSnapshot,
  SectionKind,
  ThemeMode,
  WorkspaceView,
} from "@/types/resume";
import { toast } from "sonner";

let copilotPanelModulePromise:
  | Promise<typeof import("@/components/copilot/copilot-panel")>
  | null = null;

interface AgentDraftState {
  resume: ResumeData;
  diffs: ResumeDraftDiff[];
  editCount: number;
}
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

const defaultTypography: ResumeTypographySettings = {
  fontFamily: "inter",
  fontSize: 16,
};

const defaultTemplate: ResumeTemplateId = "minimal";
const A4_WIDTH_PX = (210 / 25.4) * 96;
const A4_HEIGHT_PX = (297 / 25.4) * 96;
const PREVIEW_FRAME_GUTTER_PX = 48;
const MAX_RESUME_TITLE_LENGTH = 20;
const fontSizeOptions = [12, 14, 16, 18, 20] as const;

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
    <section className="resume-preview-card relative flex min-w-0 flex-col overflow-hidden rounded-[28px] border border-border bg-card p-4 xl:self-start">
      <div className="mb-4">
        <Skeleton className="h-3 w-24" />
      </div>
      <div className="flex justify-center">
        <div className="w-[min(100%,640px)] rounded-[24px] border border-border bg-background p-10 shadow-[0_18px_60px_rgba(15,23,42,0.10)]">
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
    <Card className="h-full rounded-[24px] border-border/80 bg-card text-card-foreground shadow-none">
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
    <section className="rounded-[26px] border border-border bg-muted/35 p-3.5 text-foreground sm:p-4">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Skeleton className="h-9 w-full max-w-[250px] rounded-full bg-card sm:max-w-[280px]" />
        <div className="ml-auto flex w-full justify-end sm:w-auto">
          <Skeleton className="h-9 w-16 rounded-full bg-background" />
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

function getWorkspacePath(view: WorkspaceView) {
  switch (view) {
    case "resume":
      return "/resume";
    case "templates":
      return "/templates";
    case "trash":
      return "/trash";
    case "models":
      return "/models";
    case "settings":
      return "/settings";
    default:
      return "/resume";
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
  return fontSizeOptions.reduce((closest, current) =>
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

function createDefaultResumeTitle(locale: Locale, index: number) {
  return locale === "zh" ? `新建简历${index}` : `New Resume ${index}`;
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

function normalizeResumeTemplateId(
  value: unknown,
  fallbackTemplateId: ResumeTemplateId,
) {
  return typeof value === "string" && value.trim()
    ? value
    : fallbackTemplateId;
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
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <span className="text-sm font-medium">{label}</span>
        <span className="rounded-lg border border-border bg-background px-2 py-1 text-sm tabular-nums">
          {value.toFixed(step < 1 ? 2 : 0)}
          {suffix ?? ""}
        </span>
      </div>
      <Slider
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

function createTemplatePreviewSection(kind: SectionKind): ResumeSection {
  return ["skills", "certificates", "languages", "other"].includes(kind)
    ? createSection(kind, "list", [createItem()])
    : createSection(kind, "timeline", [createItem()]);
}

function createDraftResumeItem(
  locale: Locale,
  index: number,
  templateId: ResumeTemplateId = defaultTemplate,
): ResumeWorkspaceItem {
  const nextResume = createEmptyResume();

  return {
    id: createId("resume"),
    title: createDefaultResumeTitle(locale, index),
    updatedAt: new Date().toISOString(),
    resume: nextResume,
    jobBrief: "",
    typography: defaultTypography,
    template: templateId,
  };
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
    value.resume.basic.name || createDefaultResumeTitle(locale, index);

  return {
    id:
      typeof value.id === "string" && value.id.trim()
        ? value.id
        : createId("resume"),
    title: normalizeResumeTitle(value.title, fallbackTitle),
    updatedAt:
      typeof value.updatedAt === "string" && value.updatedAt.trim()
        ? value.updatedAt
        : new Date().toISOString(),
    resume: value.resume,
    jobBrief: typeof value.jobBrief === "string" ? value.jobBrief : "",
    typography: normalizeResumeTypography(value.typography),
    template: normalizeResumeTemplateId(value.template, fallbackTemplateId),
    templateSettings: normalizeResumeTemplateSettings(value.templateSettings),
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
    const legacy = source as {
      savedAt?: string;
      resume: ResumeData;
      jobBrief?: string;
      typography?: ResumeTypographySettings;
      template?: ResumeTemplateId;
    };

    return [
      {
        id: `resume-${locale}-legacy`,
        title: normalizeResumeTitle(
          (legacy as { title?: unknown }).title,
          legacy.resume.basic.name || createDefaultResumeTitle(locale, 1),
        ),
        updatedAt: legacy.savedAt ?? new Date().toISOString(),
        resume: legacy.resume,
        jobBrief: legacy.jobBrief ?? "",
        typography: normalizeResumeTypography(legacy.typography),
        template: normalizeResumeTemplateId(legacy.template, fallbackTemplateId),
      },
    ];
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
      return {
        id: createId("resume"),
        title: normalizeResumeTitle(undefined, value.basic.name || "Resume"),
        updatedAt: importedAt,
        resume: value,
        jobBrief: "",
        typography: defaultTypography,
        template: fallbackTemplateId,
        templateSettings: undefined,
      };
    }

    if (!isRecord(value)) {
      return null;
    }

    const rawResume = isResumeData(value.resume) ? value.resume : null;

    if (!rawResume) {
      return null;
    }

    const typography = normalizeResumeTypography(value.typography);
    const template = normalizeResumeTemplateId(value.template, fallbackTemplateId);

    return {
      id: createId("resume"),
      title: normalizeResumeTitle(
        value.title,
        rawResume.basic.name || "Resume",
      ),
      updatedAt:
        typeof value.updatedAt === "string" ? value.updatedAt : importedAt,
      resume: rawResume,
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

function restoreResumeDocument(
  item: DeletedResumeWorkspaceItem,
): ResumeWorkspaceItem {
  const { deletedAt, ...restored } = item;

  void deletedAt;

  return restored;
}

function restoreTemplateDefinition(
  item: DeletedResumeTemplateDefinition,
): ResumeTemplateDefinition {
  const { deletedAt, ...restored } = item;

  void deletedAt;

  return {
    ...restored,
    isBuiltIn: Boolean(restored.isBuiltIn),
  };
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
      .map(([key, entryValue]) => [
        key,
        stripWorkspaceVolatileFields(entryValue),
      ]),
  );
}

function createWorkspaceFingerprint(snapshot: WorkspaceSnapshot) {
  return JSON.stringify(stripWorkspaceVolatileFields(snapshot));
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
  const [activeView, setActiveView] = useState<WorkspaceView>("resume");
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
  const [templatePreviewResume, setTemplatePreviewResume] =
    useState<ResumeData>(() => createEmptyResume());
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
    createDefaultAgentSettings([]),
  );
  const [isLoading, setIsLoading] = useState(true);
  const [hasLoadError, setHasLoadError] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">(
    "idle",
  );
  const [isResumeTitleDialogOpen, setIsResumeTitleDialogOpen] =
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
  const [agentDraft, setAgentDraft] = useState<AgentDraftState | null>(null);
  const [previewScale, setPreviewScale] = useState(1);
  const [previewPageHeight, setPreviewPageHeight] = useState(A4_HEIGHT_PX);
  const [documentStickyTop, setDocumentStickyTop] = useState(96);
  const documentHeaderRef = useRef<HTMLElement | null>(null);
  const previewScaleFrameRef = useRef<HTMLDivElement | null>(null);
  const previewRef = useRef<HTMLElement | null>(null);
  const saveRequestRef = useRef<Promise<WorkspaceSaveResponse> | null>(null);
  const pendingSaveAfterCurrentRef = useRef(false);
  const versionLoadRequestRef = useRef<string | null>(null);
  const lastPersistedSnapshotRef = useRef<string | null>(null);
  const defaultTemplateIdRef = useRef<ResumeTemplateId>(defaultTemplate);

  const effectiveResume = agentDraft?.resume ?? resume;
  const previewResume = useDeferredValue(effectiveResume);
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
  const activeTemplateDefinition = getTemplateById(templateCatalog, template);
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
  const pageHint =
    activeView === "resume"
      ? showResumeGallery
        ? t.resumeGalleryHint
        : t.resumeEditorHint
      : activeView === "templates"
        ? showTemplateGallery
          ? t.templateGalleryHint
          : t.templateEditorHint
        : activeView === "trash"
          ? t.trashHint
          : activeView === "models"
          ? t.modelsHint
          : t.settingsHint;
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
  const resumeTitleSaveLabel =
    t.saveResumeTitle || (locale === "zh" ? "保存" : "Save");
  const showEditorControls =
    activeView !== "trash" &&
    activeView !== "models" &&
    activeView !== "settings" &&
    !(
      (activeView === "resume" && showResumeGallery) ||
      (activeView === "templates" && showTemplateGallery)
    );

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
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
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

  const buildWorkspaceSnapshot = useCallback(
    (savedAt: string): WorkspaceSnapshot => {
      const persistedDocuments = resumeDocuments.map((item) =>
        item.id === activeResumeId
          ? {
              ...item,
              resume,
              jobBrief,
              template,
              templateSettings: templateSettings ?? undefined,
              typography,
              updatedAt: savedAt,
            }
          : item,
      );

      return {
        resumes: persistedDocuments,
        defaultTemplateId,
        customTemplates,
        deletedResumes: deletedResumeDocuments,
        deletedTemplates,
        modelConfigs,
        agentSettings,
        savedAt,
      };
    },
    [
      activeResumeId,
      agentSettings,
      customTemplates,
      defaultTemplateId,
      deletedResumeDocuments,
      deletedTemplates,
      jobBrief,
      modelConfigs,
      resume,
      resumeDocuments,
      template,
      templateSettings,
      typography,
    ],
  );

  const persistWorkspaceSnapshot = useCallback(
    async (snapshot: WorkspaceSnapshot) => {
      setSaveState("saving");

      try {
        const result = await saveWorkspaceSnapshotApi(
          initialLocaleRef.current,
          snapshot,
        );

        setLastSavedAt(result.savedAt);
        setActiveWorkspaceVersionId(result.versionId ?? null);
        lastPersistedSnapshotRef.current = createWorkspaceFingerprint(snapshot);
        setHasLoadError(false);

        try {
          const versions = await fetchWorkspaceVersions(initialLocaleRef.current);
          setWorkspaceVersions(versions.versions);
        } catch (versionsError) {
          console.error("Failed to refresh workspace versions.", versionsError);
        }

        setSaveState("saved");

        return result;
      } catch (error) {
        setHasLoadError(true);
        setSaveState("idle");
        throw error;
      }
    },
    [],
  );

  const saveCurrentWorkspaceSnapshot = useCallback(async () => {
    if (saveRequestRef.current) {
      pendingSaveAfterCurrentRef.current = true;
      return saveRequestRef.current;
    }

    const stableSnapshot = buildWorkspaceSnapshot(lastSavedAt ?? "");
    const stableFingerprint = createWorkspaceFingerprint(stableSnapshot);
    if (
      stableFingerprint === lastPersistedSnapshotRef.current &&
      lastSavedAt &&
      activeWorkspaceVersionId
    ) {
      setSaveState("saved");
      return {
        savedAt: lastSavedAt,
        versionId: activeWorkspaceVersionId,
      } satisfies WorkspaceSaveResponse;
    }

    const savedAt = new Date().toISOString();
    const snapshot = buildWorkspaceSnapshot(savedAt);
    const request = persistWorkspaceSnapshot(snapshot);

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
    buildWorkspaceSnapshot,
    lastSavedAt,
    persistWorkspaceSnapshot,
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
    void saveCurrentWorkspaceSnapshot();
  }, [
    isLoading,
    saveCurrentWorkspaceSnapshot,
    saveState,
  ]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "s") {
        return;
      }

      event.preventDefault();

      if (isLoading || saveState === "saving" || !showEditorControls) {
        return;
      }

      void saveCurrentWorkspaceSnapshot();
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isLoading, saveCurrentWorkspaceSnapshot, saveState, showEditorControls]);

  useEffect(() => {
    if (isLoading || saveState === "saving") {
      return;
    }

    const snapshot = buildWorkspaceSnapshot(lastSavedAt ?? "");
    const fingerprint = createWorkspaceFingerprint(snapshot);

    if (fingerprint === lastPersistedSnapshotRef.current) {
      return;
    }

    setSaveState("idle");
  }, [
    buildWorkspaceSnapshot,
    isLoading,
    lastSavedAt,
    saveState,
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
    setAgentDraft(null);
    setResume(item.resume);
    setTemplatePreviewResume(item.resume);
    setCollapsedState(createEditorCollapsedState(item.resume));
    setJobBrief(item.jobBrief);
    setTypography(item.typography ?? defaultTypography);
    setTemplate(item.template ?? defaultTemplateIdRef.current);
    setTemplateSettings(item.templateSettings ?? null);
  }, []);

  const resetResumeWorkspace = useCallback(() => {
    const emptyResume = createEmptyResume();

    setAgentDraft(null);
    setResume(emptyResume);
    setTemplatePreviewResume(emptyResume);
    setCollapsedState(createEditorCollapsedState(emptyResume));
    setJobBrief("");
    setTypography(defaultTypography);
    setTemplate(defaultTemplateIdRef.current);
    setTemplateSettings(null);
  }, []);

  const loadWorkspace = useCallback(
    async () => {
      setIsLoading(true);
      setHasLoadError(false);

      try {
        const [payload, versionsPayload] = await Promise.all([
          fetchWorkspaceBootstrap(initialLocaleRef.current),
          fetchWorkspaceVersions(initialLocaleRef.current).catch(() => ({
            versions: [] as WorkspaceVersionSummary[],
          })),
        ]);
        const workspaceSource = payload.workspace;
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
          workspaceSource,
          initialLocaleRef.current,
          requestedDefaultTemplateId,
        );
        const nextModelConfigs = normalizeModelConfigs(
          workspaceSource,
          initialLocaleRef.current,
        );
        const nextCustomTemplates = normalizeCustomTemplates(workspaceSource);
        const nextDeletedResumes = normalizeDeletedResumeDocuments(
          workspaceSource,
          requestedDefaultTemplateId,
        );
        const nextDeletedTemplates = normalizeDeletedTemplates(workspaceSource);
        const nextAgentSettings = normalizeAgentSettings(
          workspaceSource?.agentSettings,
          nextModelConfigs,
        );
        const firstResume = nextDocuments[0] ?? null;
        const loadedSnapshot: WorkspaceSnapshot = {
          resumes: nextDocuments,
          defaultTemplateId: requestedDefaultTemplateId,
          customTemplates: nextCustomTemplates,
          deletedResumes: nextDeletedResumes,
          deletedTemplates: nextDeletedTemplates,
          modelConfigs: nextModelConfigs,
          agentSettings: nextAgentSettings,
          savedAt: payload.savedAt ?? "",
        };

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
        setLastSavedAt(payload.savedAt);
        lastPersistedSnapshotRef.current =
          createWorkspaceFingerprint(loadedSnapshot);
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
          createDefaultResumeTitle(locale, index + 1) ||
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
      const result = await fetchWorkspaceVersion(
        initialLocaleRef.current,
        versionId,
      );
      const workspaceSource = result.snapshot;
      const requestedDefaultTemplateId =
        typeof workspaceSource.defaultTemplateId === "string" &&
        workspaceSource.defaultTemplateId.trim()
          ? workspaceSource.defaultTemplateId
          : defaultTemplate;
      const nextDocuments = normalizeResumeDocuments(
        workspaceSource,
        initialLocaleRef.current,
        requestedDefaultTemplateId,
      );
      const nextModelConfigs = normalizeModelConfigs(
        workspaceSource,
        initialLocaleRef.current,
      );
      const nextCustomTemplates = normalizeCustomTemplates(workspaceSource);
      const nextDeletedResumes = normalizeDeletedResumeDocuments(
        workspaceSource,
        requestedDefaultTemplateId,
      );
      const nextDeletedTemplates = normalizeDeletedTemplates(workspaceSource);
      const nextAgentSettings = normalizeAgentSettings(
        workspaceSource.agentSettings,
        nextModelConfigs,
      );
      const firstResume = nextDocuments[0] ?? null;
      const nextActiveResume =
        (activeResumeId &&
          nextDocuments.find((item) => item.id === activeResumeId)) ||
        firstResume;

      setResumeDocuments(nextDocuments);
      setActiveResumeId(nextActiveResume?.id ?? null);
      if (nextActiveResume) {
        hydrateResumeWorkspace(nextActiveResume);
      } else {
        resetResumeWorkspace();
      }
      setDefaultTemplateId(requestedDefaultTemplateId);
      setCustomTemplates(nextCustomTemplates);
      setDeletedResumeDocuments(nextDeletedResumes);
      setDeletedTemplates(nextDeletedTemplates);
      setModelConfigs(nextModelConfigs);
      setAgentSettings(nextAgentSettings);
      setLastSavedAt(workspaceSource.savedAt);
      setActiveWorkspaceVersionId(result.versionId);
      lastPersistedSnapshotRef.current = createWorkspaceFingerprint({
        resumes: nextDocuments,
        defaultTemplateId: requestedDefaultTemplateId,
        customTemplates: nextCustomTemplates,
        deletedResumes: nextDeletedResumes,
        deletedTemplates: nextDeletedTemplates,
        modelConfigs: nextModelConfigs,
        agentSettings: nextAgentSettings,
        savedAt: workspaceSource.savedAt,
      });
      setSaveState("saved");

      if (isResumeDetailView && nextActiveResume) {
        navigate(getResumePath(nextActiveResume.id), { replace: true });
      } else if (isResumeDetailView) {
        navigate("/resume", { replace: true });
      }
    } catch (error) {
      console.error("Failed to load workspace version.", error);
      setHasLoadError(true);
      setSaveState("idle");
    } finally {
      versionLoadRequestRef.current = null;
      setIsLoading(false);
    }
  }

  useEffect(() => {
    setAgentSettings((current) =>
      normalizeAgentSettings(current, modelConfigs),
    );
  }, [modelConfigs]);

  useEffect(() => {
    const hasActiveTemplate = templateCatalog.some(
      (item) => item.id === template,
    );
    const hasDefaultTemplate = templateCatalog.some(
      (item) => item.id === defaultTemplateId,
    );

    if (!hasActiveTemplate) {
      setTemplate(defaultTemplate);
    }

    if (!hasDefaultTemplate) {
      setDefaultTemplateId(defaultTemplate);
    }

    if (hasActiveTemplate && hasDefaultTemplate) {
      return;
    }

    const fallbackTemplateId = hasDefaultTemplate
      ? defaultTemplateId
      : defaultTemplate;

    setResumeDocuments((current) =>
      current.map((item) =>
        item.template &&
        !templateCatalog.some((entry) => entry.id === item.template)
          ? { ...item, template: fallbackTemplateId }
          : item,
      ),
    );
  }, [defaultTemplateId, template, templateCatalog]);

  function openResumeEditor(resumeId: string) {
    const targetResume = resumeDocuments.find((item) => item.id === resumeId);

    if (!targetResume) {
      return;
    }

    setActiveResumeId(resumeId);
    hydrateResumeWorkspace(targetResume);
    setActiveView("resume");
    setShowResumeGallery(false);
    runViewTransition(() => navigate(getResumePath(resumeId)), "nav-forward");
  }

  function openTemplateEditor(templateId: string) {
    if (!templateCatalog.some((item) => item.id === templateId)) {
      return;
    }

    setTemplate(templateId);
    setActiveView("templates");
    setShowTemplateGallery(false);
    runViewTransition(() => navigate(getTemplatePath(templateId)), "nav-forward");
  }

  async function createResume() {
    if (isLoading || saveState === "saving") {
      return;
    }

    const nextItem = createDraftResumeItem(
      locale,
      resumeDocuments.length + 1,
      defaultTemplateId,
    );
    const savedAt = new Date().toISOString();
    const currentDocuments = resumeDocuments.map((item) =>
      item.id === activeResumeId
        ? {
            ...item,
            resume,
            jobBrief,
            template,
            templateSettings: templateSettings ?? undefined,
            typography,
            updatedAt: savedAt,
          }
        : item,
    );
    const nextDocuments = [...currentDocuments, nextItem];
    const nextSnapshot: WorkspaceSnapshot = {
      resumes: nextDocuments,
      defaultTemplateId,
      customTemplates,
      deletedResumes: deletedResumeDocuments,
      deletedTemplates,
      modelConfigs,
      agentSettings,
      savedAt,
    };

    try {
      await persistWorkspaceSnapshot(nextSnapshot);
    } catch (error) {
      console.error("Failed to create resume in backend.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.loadError, {
          closeButton: true,
        });
      }
      return;
    }

    setResumeDocuments(nextDocuments);
    setActiveResumeId(nextItem.id);
    hydrateResumeWorkspace(nextItem);
    setActiveView("resume");
    setShowResumeGallery(false);
    runViewTransition(() => navigate(getResumePath(nextItem.id)), "nav-forward");
  }

  async function importResume(file: File) {
    try {
      const payload = await importResumePayload(file);
      const importedDocuments = normalizeImportedResumeDocuments(
        payload,
        defaultTemplateId,
      );

      if (importedDocuments.length === 0) {
        throw new Error(
          "No valid resume documents found in the imported file.",
        );
      }

      const firstImportedResume = importedDocuments[0];
      const savedAt = new Date().toISOString();
      const currentDocuments = resumeDocuments.map((item) =>
        item.id === activeResumeId
          ? {
              ...item,
              resume,
              jobBrief,
              template,
              templateSettings: templateSettings ?? undefined,
              typography,
              updatedAt: savedAt,
            }
          : item,
      );
      const nextDocuments = [...currentDocuments, ...importedDocuments];
      const nextSnapshot: WorkspaceSnapshot = {
        resumes: nextDocuments,
        defaultTemplateId,
        customTemplates,
        deletedResumes: deletedResumeDocuments,
        deletedTemplates,
        modelConfigs,
        agentSettings,
        savedAt,
      };

      await persistWorkspaceSnapshot(nextSnapshot);

      setResumeDocuments(nextDocuments);
      setActiveResumeId(firstImportedResume.id);
      hydrateResumeWorkspace(firstImportedResume);
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
      console.error("Failed to import resume JSON.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.importResumeFailed, {
          closeButton: true,
        });
      }
    }
  }

  const previewAgentEdits = useCallback(
    (edits: AgentResumeEditSuggestion[], baseResume = resume) => {
      const result = applyAgentEditsToDraft(baseResume, edits);

      if (result.appliedCount === 0) {
        return;
      }

      setAgentDraft({
        resume: result.resume,
        diffs: result.diffs,
        editCount: result.appliedCount,
      });
    },
    [resume],
  );

  const applyAgentDraft = useCallback(() => {
    if (!agentDraft) {
      return;
    }

    setResume(agentDraft.resume);
    setTemplatePreviewResume(agentDraft.resume);
    setCollapsedState(createEditorCollapsedState(agentDraft.resume));
    setAgentDraft(null);
    toast.success(t.agentDraftApplied, {
      closeButton: true,
    });
  }, [agentDraft, t]);

  const discardAgentDraft = useCallback(() => {
    if (!agentDraft) {
      return;
    }

    setAgentDraft(null);
    toast.success(t.agentDraftDiscarded, {
      closeButton: true,
    });
  }, [agentDraft, t]);

  function moveResumesToTrash(resumeIds: string[]) {
    if (resumeIds.length === 0) {
      return;
    }

    const deletedAt = new Date().toISOString();
    const removing = resumeDocuments.filter((item) =>
      resumeIds.includes(item.id),
    );
    const remaining = resumeDocuments.filter(
      (item) => !resumeIds.includes(item.id),
    );

    if (removing.length === 0) {
      return;
    }

    const nextActiveResume =
      remaining.find((item) => item.id === activeResumeId) ??
      remaining[0] ??
      null;

    setResumeDocuments(remaining);
    setDeletedResumeDocuments((previous) => [
      ...removing.map((item) => ({ ...item, deletedAt })),
      ...previous,
    ]);

    if (activeResumeId && resumeIds.includes(activeResumeId)) {
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
    }

    toast.success(resumeIds.length > 1 ? t.resumesDeleted : t.resumeDeleted, {
      closeButton: true,
    });
  }

  function restoreResumes(resumeIds: string[]) {
    if (resumeIds.length === 0) {
      return;
    }

    const restoring = deletedResumeDocuments.filter((item) =>
      resumeIds.includes(item.id),
    );

    if (restoring.length === 0) {
      return;
    }

    setDeletedResumeDocuments((current) =>
      current.filter((item) => !resumeIds.includes(item.id)),
    );
    setResumeDocuments((current) => [
      ...restoring.map(restoreResumeDocument),
      ...current,
    ]);

    toast.success(resumeIds.length > 1 ? t.resumesRestored : t.resumeRestored, {
      closeButton: true,
    });
  }

  function permanentlyDeleteResumes(resumeIds: string[]) {
    if (resumeIds.length === 0) {
      return;
    }

    setDeletedResumeDocuments((current) =>
      current.filter((item) => !resumeIds.includes(item.id)),
    );
    toast.success(
      resumeIds.length > 1 ? t.resumesDeletedForever : t.resumeDeletedForever,
      {
        closeButton: true,
      },
    );
  }

  function emptyResumeTrash() {
    if (deletedResumeDocuments.length === 0) {
      return;
    }

    setDeletedResumeDocuments([]);
    toast.success(t.resumeTrashEmptied, {
      closeButton: true,
    });
  }

  function createCustomTemplate() {
    const nextTemplate = createCustomTemplateFromBase(
      activeTemplateDefinition,
      {
        name: `${t.customTemplate} ${customTemplates.length + 1}`,
      },
    );

    setCustomTemplates((current) => [...current, nextTemplate]);
    setTemplate(nextTemplate.id);
    setActiveView("templates");
    setShowTemplateGallery(false);
    runViewTransition(
      () => navigate(getTemplatePath(nextTemplate.id)),
      "nav-forward",
    );
    toast.success(t.templateCreated, {
      closeButton: true,
    });
  }

  async function importTemplates(file: File) {
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

      setCustomTemplates((current) => [...current, ...importedTemplates]);
      setTemplate(importedTemplates[0].id);
      setActiveView("templates");
      setShowTemplateGallery(false);
      runViewTransition(
        () => navigate(getTemplatePath(importedTemplates[0].id)),
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

  function deleteTemplates(templateIds: string[]) {
    if (templateIds.length === 0) {
      return;
    }

    const deletedAt = new Date().toISOString();
    const removing = templateCatalog.filter((item) =>
      templateIds.includes(item.id),
    );
    const fallbackTemplateId = templateIds.includes(defaultTemplateId)
      ? defaultTemplate
      : defaultTemplateId;

    setCustomTemplates((current) =>
      current.filter((item) => !templateIds.includes(item.id)),
    );
    setDeletedTemplates((current) => [
      ...removing.map((item) => ({ ...item, deletedAt })),
      ...current,
    ]);
    setResumeDocuments((current) =>
      current.map((item) =>
        item.template && templateIds.includes(item.template)
          ? { ...item, template: fallbackTemplateId }
          : item,
      ),
    );

    if (templateIds.includes(defaultTemplateId)) {
      setDefaultTemplateId(defaultTemplate);
    }

    if (templateIds.includes(template)) {
      setTemplate(fallbackTemplateId);
    }

    toast.success(
      templateIds.length > 1 ? t.templatesDeleted : t.templateDeleted,
      {
        closeButton: true,
      },
    );
  }

  function restoreTemplates(templateIds: string[]) {
    if (templateIds.length === 0) {
      return;
    }

    const restoring = deletedTemplates.filter((item) =>
      templateIds.includes(item.id),
    );

    if (restoring.length === 0) {
      return;
    }

    setDeletedTemplates((current) =>
      current.filter((item) => !templateIds.includes(item.id)),
    );
    setCustomTemplates((current) => [
      ...restoring
        .filter((item) => !item.isBuiltIn)
        .map(restoreTemplateDefinition),
      ...current,
    ]);

    toast.success(
      templateIds.length > 1 ? t.templatesRestored : t.templateRestored,
      {
        closeButton: true,
      },
    );
  }

  function permanentlyDeleteTemplates(templateIds: string[]) {
    if (templateIds.length === 0) {
      return;
    }

    setDeletedTemplates((current) =>
      current.filter((item) => !templateIds.includes(item.id)),
    );
    toast.success(
      templateIds.length > 1
        ? t.templatesDeletedForever
        : t.templateDeletedForever,
      {
        closeButton: true,
      },
    );
  }

  function emptyTemplateTrash() {
    if (deletedTemplates.length === 0) {
      return;
    }

    setDeletedTemplates([]);
    toast.success(t.templateTrashEmptied, {
      closeButton: true,
    });
  }

  function handleSetDefaultTemplate(templateId: string) {
    if (!templateCatalog.some((item) => item.id === templateId)) {
      return;
    }

    setDefaultTemplateId(templateId);
    toast.success(t.defaultTemplateUpdated, {
      closeButton: true,
    });
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

  function handleViewChange(view: WorkspaceView) {
    preloadWorkspaceView(view);

    runViewTransition(() => {
      setActiveView(view);
      setShowResumeGallery(view === "resume");
      setShowTemplateGallery(view === "templates");
      navigate(getWorkspacePath(view));
    }, "nav-lateral");
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

  function updateCustomField(
    id: string,
    field: keyof Omit<CustomField, "id">,
    value: string,
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
            { id: createId("field"), label: "", value: "" },
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

  function addTemplatePreviewSection(kind: SectionKind) {
    const nextSection = createTemplatePreviewSection(kind);

    startTransition(() => {
      setTemplatePreviewResume((current) => ({
        ...current,
        sections: [...current.sections, nextSection],
      }));
    });
  }

  function removeTemplatePreviewSection(sectionId: string) {
    startTransition(() => {
      setTemplatePreviewResume((current) => ({
        ...current,
        sections: current.sections.filter((section) => section.id !== sectionId),
      }));
    });
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

  async function exportPdf() {
    if (isExporting || !activeResumeId) {
      return;
    }

    setIsExporting(true);

    try {
      const savedVersion = await saveCurrentWorkspaceSnapshot();
      const result = await requestResumePdfExport({
        resumeId: activeResumeId,
        locale,
        savedAt: savedVersion.savedAt,
        versionId: savedVersion.versionId,
        fileNameSeed: `${activeResumeTitle || resume.basic.name || "resume"}-${locale}-${template}`,
        renderBaseUrl: window.location.origin,
      });

      await downloadExportedPdf(result);
      toast.success(t.exportSuccess, {
        closeButton: true,
      });
    } catch (error) {
      console.error("Failed to export resume PDF.", error);
      if (!isApiErrorToastShown(error)) {
        toast.error(t.exportFailed, {
          closeButton: true,
        });
      }
    } finally {
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
        className="resume-preview-card relative flex min-w-0 flex-col overflow-x-hidden rounded-[28px] border border-border bg-card p-4 print:overflow-visible print:border-0 print:bg-white print:p-0 xl:self-start"
      >
        <div className="mb-4 print:hidden">
          <p className="text-[11px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
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
                  locale={locale}
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
    const tooltip = isAgentPanelCollapsed
      ? t.agentExpandPanel
      : t.agentCollapsePanel;
    const RailIcon = isAgentPanelCollapsed
      ? ChevronLeft
      : ChevronRight;
    const railHeight = previewPageHeight * previewScale + 64;
    const railStyle = {
      "--agent-seam-rail-height": `${railHeight}px`,
    } as CSSProperties;

    return (
      <div
        className={cn(
          "agent-seam-rail hidden print:hidden 2xl:flex",
          isAgentPanelCollapsed && "agent-seam-rail--collapsed",
        )}
        style={railStyle}
      >
        <TooltipProvider delayDuration={180}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={tooltip}
                className="agent-seam-rail-button"
                onClick={() =>
                  setIsAgentPanelCollapsed((current) => !current)
                }
              >
                <span className="agent-seam-rail-track" aria-hidden="true">
                  <RailIcon className="agent-seam-rail-icon" />
                </span>
              </button>
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
      return (
        <GalleryRouteSkeleton
          itemCount={skeletonItemCount}
          includeCreateCard
        />
      );
    }

    return (
      <main className="flex-1 p-4">
        <Suspense
          fallback={
            <GalleryWorkspaceSkeleton
              itemCount={skeletonItemCount}
              includeCreateCard
            />
          }
        >
          <ResumeGallery
            locale={locale}
            t={t}
            resumes={resumeDocuments}
            templates={templateCatalog}
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
            locale={locale}
            t={t}
            resume={deferredTemplatePreviewResume}
            templates={templateCatalog}
            defaultTemplateId={defaultTemplateId}
            activeTemplateId={template}
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
          onRestoreResume={restoreResumes}
          onDeleteResumeForever={permanentlyDeleteResumes}
          onEmptyResumeTrash={emptyResumeTrash}
          onRestoreTemplate={restoreTemplates}
          onDeleteTemplateForever={permanentlyDeleteTemplates}
          onEmptyTemplateTrash={emptyTemplateTrash}
        />
      </Suspense>
    );
  }

  function renderResumeWorkspace() {
    const shouldDockAgent = !isAgentPanelCollapsed;
    const resumeWorkspaceStyle = {
      "--resume-workspace-columns": shouldDockAgent
        ? "440px minmax(0,1fr) 18px 360px"
        : "440px minmax(0,1fr) 18px 0px",
    } as CSSProperties;
    const renderCopilotPanel = (mode: "docked" | "sheet") => (
      <Suspense
        fallback={
          <Card className="h-[calc(100svh-7rem)] min-h-[720px] rounded-[32px] border-border/60">
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
          key={`${activeResumeId ?? "resume"}-${locale}-${mode}`}
          mode={mode}
          resumeId={activeResumeId ?? undefined}
          t={t}
          locale={locale}
          resume={previewResume}
          jobBrief={jobBrief}
          onJobBriefChange={setJobBrief}
          keywordMatch={keywordMatch}
          modelConfigs={modelConfigs}
          selectedModelId={agentSettings.defaultModelId}
          agentSettings={agentSettings}
          onSelectedModelChange={(modelId) =>
            setAgentSettings((current) => ({
              ...current,
              defaultModelId: modelId,
            }))
          }
          hasAgentDraft={Boolean(agentDraft)}
          onPreviewAgentEdits={previewAgentEdits}
          onApplyAgentDraft={applyAgentDraft}
          onDiscardAgentDraft={discardAgentDraft}
          onOpenModelSettings={() => handleViewChange("models")}
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

        <aside
          aria-hidden={!shouldDockAgent}
          className={cn(
            "relative hidden min-w-0 overflow-hidden print:hidden 2xl:block 2xl:self-start",
            "transition-opacity duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]",
            !shouldDockAgent && "pointer-events-none opacity-0",
          )}
        >
          {renderCopilotPanel("docked")}
        </aside>
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
              locale={locale}
              t={t}
              resume={deferredTemplatePreviewResume}
              templates={templateCatalog}
              defaultTemplateId={defaultTemplateId}
              activeTemplateId={template}
              onOpenTemplate={openTemplateEditor}
              onSetDefaultTemplate={handleSetDefaultTemplate}
              onCreateCustomTemplate={createCustomTemplate}
              onImportTemplates={(file) => {
                void importTemplates(file);
              }}
              onUpdateTemplate={updateCustomTemplate}
              onDeleteTemplate={(templateId) => deleteTemplates([templateId])}
              onBulkDeleteTemplates={deleteTemplates}
              onAddPreviewSection={addTemplatePreviewSection}
              onRemovePreviewSection={removeTemplatePreviewSection}
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
            onChange={setModelConfigs}
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
          onThemeChange={setTheme}
          onLocaleChange={onLocaleChange}
          fontFamily={typography.fontFamily}
          onFontFamilyChange={(value) =>
            setTypography((current) => ({
              ...current,
              fontFamily: value,
            }))
          }
          fontSize={typography.fontSize}
          onFontSizeChange={(value) =>
            setTypography((current) => ({
              ...current,
              fontSize: value,
            }))
          }
          agentSettings={agentSettings}
          onAgentSettingsChange={setAgentSettings}
          modelConfigs={modelConfigs}
          onOpenModelConfigs={() =>
            runViewTransition(() => navigate("/models"), "nav-lateral")
          }
          onPasswordChanged={onLogout}
        />
      </Suspense>
    );
  }

  return (
    <SidebarProvider>
      <Toaster theme={theme} position="bottom-right" closeButton />
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
        <DialogContent showCloseButton className="w-[min(420px,calc(100vw-2rem))]">
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

      <AppSidebar
        t={t}
        activeView={activeView}
        onViewChange={handleViewChange}
        onViewPreload={preloadWorkspaceView}
      />

      <SidebarInset
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
          className="sticky top-0 z-20 flex min-h-20 flex-wrap items-center justify-between gap-3 border-b border-border bg-background px-4 py-3 print:hidden"
          style={{ viewTransitionName: "persistent-header" }}
        >
          <div className="flex items-center gap-3">
            <SidebarTrigger />
            {isResumeDetailView || isTemplateDetailView ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-9 rounded-full border-border/80 bg-card px-3 shadow-sm"
                onClick={() => {
                  if (isResumeDetailView) {
                    runViewTransition(() => navigate("/resume"), "nav-back");
                    return;
                  }

                  runViewTransition(() => navigate("/templates"), "nav-back");
                }}
              >
                <ChevronLeft className="size-4" />
                {isResumeDetailView ? t.backToResumes : t.backToTemplates}
              </Button>
            ) : null}
            <div>
              {!isResumeDetailView && !isTemplateDetailView ? (
                <p className="text-sm font-semibold text-foreground">
                  {pageEyebrow}
                </p>
              ) : null}
              {!isResumeDetailView && !isTemplateDetailView ? (
                <p className="mt-0.5 hidden text-[11px] text-muted-foreground xl:block">
                  {pageHint}
                </p>
              ) : null}
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-end gap-2">
            {isResumeDetailView ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                title={activeResumeToolbarTitle}
                aria-label={t.editResumeTitle}
                className="h-10 min-w-[88px] justify-start rounded-lg border-0 bg-transparent px-2 text-sm font-semibold shadow-none hover:bg-accent/60"
                onClick={openResumeTitleDialog}
              >
                <span className="max-w-[72px] overflow-hidden whitespace-nowrap">
                  {formatResumeTitleForToolbar(activeResumeToolbarTitle)}
                </span>
                <Pencil className="size-3.5 text-muted-foreground" />
              </Button>
            ) : null}
            <SegmentTabs
              icon={<Languages className="size-4" />}
              label={t.language}
              items={[
                {
                  key: "zh",
                  label: "中文",
                  active: locale === "zh",
                  onClick: () => onLocaleChange("zh"),
                },
                {
                  key: "en",
                  label: "EN",
                  active: locale === "en",
                  onClick: () => onLocaleChange("en"),
                },
              ]}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              title={t.themeToggleLabel}
              aria-label={t.themeToggleLabel}
              onClick={() =>
                setTheme((current) => (current === "light" ? "dark" : "light"))
              }
            >
              {theme === "dark" ? (
                <Sun className="size-4" />
              ) : (
                <Moon className="size-4" />
              )}
            </Button>

            {showEditorControls && isResumeDetailView ? (
              <TooltipProvider>
                <>
                  <Popover>
                    <PopoverTrigger
                      type="button"
                      className={cn(buttonVariants({ variant: "outline" }))}
                    >
                      <SlidersHorizontal className="size-4" />
                      {t.format}
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-[340px] p-3">
                      <div className="grid gap-3">
                        <label className="grid gap-2">
                          <span className="text-sm font-medium">
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
                            <SelectTrigger>
                              <div className="flex min-w-0 items-center gap-2">
                                <Type className="size-4 text-muted-foreground" />
                                <SelectValue />
                              </div>
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
                        </label>

                        <label className="grid gap-2">
                          <span className="text-sm font-medium">
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
                            <SelectTrigger>
                              <div className="flex min-w-0 items-center gap-2">
                                <ALargeSmall className="size-4 text-muted-foreground" />
                                <SelectValue />
                              </div>
                            </SelectTrigger>
                            <SelectContent>
                              {fontSizeOptions.map((size) => (
                                <SelectItem key={size} value={String(size)}>
                                  {size}pt
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </label>

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

                  <div className="inline-flex h-10 items-center gap-1.5 whitespace-nowrap rounded-lg border border-border bg-card pl-2 pr-0.5 text-sm">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex size-7 items-center justify-center rounded-md text-muted-foreground">
                          <LayoutTemplate className="size-3.5" />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>{t.applyTemplate}</TooltipContent>
                    </Tooltip>
                    <Select
                      value={template}
                      onValueChange={applyTemplateToActiveResume}
                    >
                      <SelectTrigger className="h-8 w-[106px] min-w-[106px] border-0 bg-transparent px-1 shadow-none focus-visible:ring-0">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent
                        align="start"
                        position="popper"
                        sideOffset={6}
                      >
                        {templateCatalog.map((item) => (
                          <SelectItem key={item.id} value={item.id}>
                            {item.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </>
              </TooltipProvider>
            ) : null}

            {showEditorControls ? (
              <SaveStatusButton
                locale={locale}
                label={t.saveStatus}
                savingText={t.saving}
                savedText={t.saved}
                unsavedText={t.unsaved}
                lastSavedLabel={t.lastSavedAt}
                state={saveState}
                lastSavedAt={lastSavedAt}
                versions={workspaceVersions}
                activeVersionId={activeWorkspaceVersionId}
                versionsLabel={t.saveVersions}
                currentVersionLabel={t.currentVersion}
                noVersionsText={t.noSaveVersions}
                onSave={() => void saveCurrentWorkspaceSnapshot()}
                onSelectVersion={(versionId) =>
                  void selectWorkspaceVersion(versionId)
                }
              />
            ) : null}

            {showEditorControls ? (
              <Button
                type="button"
                variant="outline"
                onClick={() => void exportPdf()}
                disabled={isExporting || isLoading}
              >
                <Download
                  className={cn("size-4", isExporting && "animate-pulse")}
                />
                {isExporting ? t.exporting : t.exportPdf}
              </Button>
            ) : null}

            <Button type="button" variant="outline" onClick={onLogout}>
              <LogOut className="size-4" />
              {t.logout}
            </Button>
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

function SegmentTabs({
  icon,
  label,
  items,
}: {
  icon: ReactNode;
  label: string;
  items: Array<{
    key: string;
    label: string;
    active: boolean;
    onClick: () => void;
  }>;
}) {
  return (
    <div className="flex h-10 items-center gap-1 rounded-lg border border-border bg-card p-1">
      <span className="pl-2 text-muted-foreground">{icon}</span>
      <span className="sr-only">{label}</span>
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={item.onClick}
          className={cn(
            "rounded-md px-2.5 py-1.5 text-sm transition-colors",
            item.active
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
