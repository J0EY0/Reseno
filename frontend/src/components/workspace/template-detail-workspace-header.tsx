import { ChevronLeft, Languages, LogOut, Moon, Sun } from "lucide-react";
import type { RefObject } from "react";

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
import { SidebarTrigger } from "@/components/ui/sidebar";
import type { TemplateDetailSaveState } from "@/components/workspace/use-template-detail-save";
import type { AppMessages, Locale } from "@/i18n";
import type { WorkspaceVersionSummary } from "@/types/api";
import type { ResumeTemplateDefinition, ThemeMode } from "@/types/resume";

const noWorkspaceVersions: WorkspaceVersionSummary[] = [];

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

  return (
    <header
      ref={headerRef}
      className="sticky top-0 z-20 flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-border bg-background px-4 py-2 print:hidden"
      style={{ viewTransitionName: "persistent-header" }}
    >
      <div className="flex min-w-0 items-center gap-2">
        <SidebarTrigger
          className="-ml-1"
          aria-label={messages.toggleSidebar}
          title={messages.toggleSidebar}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onBack}
        >
          <ChevronLeft className="size-4" />
          {messages.backToTemplates}
        </Button>
        <h1 className="max-w-48 truncate text-sm font-medium text-foreground">
          {template?.name ?? messages.resumeTemplates}
        </h1>
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
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
    </header>
  );
}
