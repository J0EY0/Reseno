import {
  ChevronLeft,
  Ellipsis,
  Languages,
  LogOut,
  Moon,
  Sun,
} from "lucide-react";
import { lazy, Suspense, type RefObject } from "react";

import { SaveStatusButton } from "@/components/save-status-button";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { TemplateDetailSaveState } from "@/components/workspace/use-template-detail-save";
import { useMediaQuery } from "@/hooks/use-media-query";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspaceVersionSummary } from "@/types/api";
import type { ResumeTemplateDefinition, ThemeMode } from "@/types/resume";

const noWorkspaceVersions: WorkspaceVersionSummary[] = [];

const WorkspaceMobileActionsMenu = lazy(() =>
  import("@/components/workspace/workspace-mobile-actions-menu").then(
    ({ WorkspaceMobileActionsMenu: Component }) => ({ default: Component }),
  ),
);
const MOBILE_HEADER_MEDIA_QUERY = "(max-width: 767px)";

export function TemplateDetailWorkspaceHeader({
  changeCount,
  headerRef,
  lastSavedAt,
  locale,
  messages,
  onBack,
  onLocaleChange,
  onLogout,
  onSave,
  onThemeChange,
  resolvedTheme,
  saveState,
  template,
}: {
  changeCount: number;
  headerRef: RefObject<HTMLElement | null>;
  lastSavedAt: string | null;
  locale: Locale;
  messages: AppMessages;
  onBack: () => void;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  onSave: () => Promise<unknown>;
  onThemeChange: (theme: ThemeMode) => void;
  resolvedTheme: "light" | "dark";
  saveState: TemplateDetailSaveState;
  template: ResumeTemplateDefinition | null;
}) {
  const canSave = Boolean(template && !template.isBuiltIn);
  const isMobile = useMediaQuery(MOBILE_HEADER_MEDIA_QUERY);

  return (
    <header
      ref={headerRef}
      className="sticky top-0 z-20 grid h-16 shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 border-b border-border bg-background px-3 print:hidden sm:px-4 md:gap-3"
    >
      <div className="flex min-w-0 items-center gap-2">
        <Button
          type="button"
          variant="outline"
          className="px-2.5 sm:px-3"
          aria-label={messages.backToTemplates}
          title={messages.backToTemplates}
          onClick={onBack}
        >
          <ChevronLeft className="size-4" />
          <span className="hidden sm:inline">{messages.backToTemplates}</span>
        </Button>
        <h1 className="truncate text-sm font-medium text-foreground md:max-w-48">
          {template?.name ?? messages.resumeTemplates}
        </h1>
      </div>

      <div className="hidden flex-wrap items-center justify-end gap-2 md:flex">
        {canSave ? (
          <SaveStatusButton
            locale={locale}
            label={messages.saveStatus}
            savingText={messages.saving}
            savedText={messages.saved}
            unsavedText={messages.unsaved}
            lastSavedLabel={messages.lastSavedAt}
            state={saveState}
            hasUnsavedChanges={changeCount > 0}
            lastSavedAt={lastSavedAt}
            versions={noWorkspaceVersions}
            activeVersionId={null}
            versionsLabel={messages.saveVersions}
            currentVersionLabel={messages.currentVersion}
            noVersionsText={messages.noSaveVersions}
            onSave={() => void onSave()}
            onSelectVersion={() => undefined}
            showVersions={false}
          />
        ) : null}

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
            aria-label={messages.language}
          >
            <Languages className="text-foreground" aria-hidden="true" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end" position="popper" sideOffset={4}>
            <SelectGroup>
              <SelectItem value="zh">{messages.languageChinese}</SelectItem>
              <SelectItem value="en">{messages.languageEnglish}</SelectItem>
            </SelectGroup>
          </SelectContent>
        </Select>

        <Button
          type="button"
          variant="outline"
          size="icon"
          title={messages.themeToggleLabel}
          aria-label={messages.themeToggleLabel}
          onClick={() =>
            onThemeChange(resolvedTheme === "dark" ? "light" : "dark")
          }
        >
          {resolvedTheme === "dark" ? (
            <Sun className="size-4" />
          ) : (
            <Moon className="size-4" />
          )}
        </Button>
        <Button type="button" variant="outline" onClick={onLogout}>
          <LogOut className="size-4" />
          {messages.logout}
        </Button>
      </div>

      <div className="flex items-center gap-2 md:hidden">
        {canSave ? (
          <SaveStatusButton
            locale={locale}
            label={messages.saveStatus}
            savingText={messages.saving}
            savedText={messages.saved}
            unsavedText={messages.unsaved}
            lastSavedLabel={messages.lastSavedAt}
            state={saveState}
            hasUnsavedChanges={changeCount > 0}
            lastSavedAt={lastSavedAt}
            versions={noWorkspaceVersions}
            activeVersionId={null}
            versionsLabel={messages.saveVersions}
            currentVersionLabel={messages.currentVersion}
            noVersionsText={messages.noSaveVersions}
            onSave={() => void onSave()}
            onSelectVersion={() => undefined}
            showVersions={false}
          />
        ) : null}
        {isMobile ? (
          <Suspense
            fallback={
              <Button
                type="button"
                variant="outline"
                size="icon"
                aria-label={messages.actions}
                title={messages.actions}
                disabled
              >
                <Ellipsis />
              </Button>
            }
          >
            <WorkspaceMobileActionsMenu
              locale={locale}
              messages={messages}
              onLocaleChange={onLocaleChange}
              onLogout={onLogout}
              onThemeChange={onThemeChange}
              resolvedTheme={resolvedTheme}
            />
          </Suspense>
        ) : null}
      </div>
    </header>
  );
}
