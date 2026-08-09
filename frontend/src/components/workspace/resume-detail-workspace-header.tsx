import {
  Bot,
  ChevronDown,
  ChevronLeft,
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
  Sun,
} from "lucide-react";
import type { RefObject } from "react";

import { ResumeFormatPopover } from "@/components/editor/resume-format-popover";
import { SaveStatusButton } from "@/components/save-status-button";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { SidebarTrigger } from "@/components/ui/sidebar";
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import type { AppMessages, Locale } from "@/i18n";
import { formatResumeTitleForToolbar } from "@/lib/resume-title";

function ResumeDetailEditorActions({
  locale,
  messages,
  model,
}: {
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
}) {
  const { commands, state } = model;

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {!state.agent.isDockLayout ? (
        <Button
          type="button"
          variant="outline"
          aria-label={messages.agentExpandPanel}
          onFocus={() => void import("@/components/copilot/copilot-panel")}
          onPointerEnter={() =>
            void import("@/components/copilot/copilot-panel")
          }
          onClick={() => commands.agent.setSheetOpen(true)}
        >
          <Bot data-icon="inline-start" />
          {messages.aiTitle}
        </Button>
      ) : null}

      <Button
        type="button"
        variant="outline"
        onClick={() => void commands.fitOnePage()}
        disabled={
          state.document.isSmartFittingOnePage ||
          !state.document.isPreviewReady
        }
        title={messages.smartOnePage}
        aria-label={messages.smartOnePage}
      >
        {state.document.isSmartFittingOnePage ? (
          <Spinner
            data-icon="inline-start"
            aria-label={messages.smartOnePage}
          />
        ) : (
          <Minimize2 data-icon="inline-start" />
        )}
        {messages.smartOnePage}
      </Button>

      <ResumeFormatPopover
        t={messages}
        template={state.template}
        templates={state.templates}
        typography={state.typography}
        settings={state.activeTemplate.settings}
        hasTemplateStyleOverrides={state.hasTemplateStyleOverrides}
        onRestoreTemplateDefaults={commands.restoreTemplateDefaults}
        onTemplateChange={commands.applyTemplate}
        onTypographyChange={commands.updateTypography}
        onTemplateSettingsChange={commands.updateTemplateSettings}
      />

      <Button
        type="button"
        variant="outline"
        onClick={() => void commands.duplicateResume()}
        disabled={
          state.isDuplicatingResume ||
          state.isLoading ||
          state.save.state === "saving"
        }
      >
        {state.isDuplicatingResume ? (
          <Spinner data-icon="inline-start" />
        ) : (
          <CopyPlus data-icon="inline-start" />
        )}
        {messages.duplicateResume}
      </Button>

      <SaveStatusButton
        locale={locale}
        label={messages.saveStatus}
        savingText={messages.saving}
        savedText={messages.saved}
        unsavedText={messages.unsaved}
        lastSavedLabel={messages.lastSavedAt}
        state={state.save.state}
        hasUnsavedChanges={state.save.changeCount > 0}
        lastSavedAt={state.save.lastSavedAt}
        versions={state.save.versions}
        activeVersionId={state.save.activeVersionId}
        versionsLabel={messages.saveVersions}
        currentVersionLabel={messages.currentVersion}
        noVersionsText={messages.noSaveVersions}
        onSave={() => void commands.save()}
        onSelectVersion={commands.selectVersion}
        showVersions
      />

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            disabled={state.isExporting || state.isLoading}
          >
            {state.isExporting ? (
              <Spinner
                data-icon="inline-start"
                aria-label={messages.exporting}
              />
            ) : (
              <Download data-icon="inline-start" />
            )}
            {state.isExporting ? messages.exporting : messages.export}
            {!state.isExporting ? (
              <ChevronDown
                data-icon="inline-end"
                className="opacity-50"
              />
            ) : null}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuGroup>
            <DropdownMenuItem onSelect={() => void commands.exportPdf()}>
              <FileText />
              {messages.exportPdf}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void commands.exportImages()}>
              <Images />
              {messages.exportImages}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void commands.exportJson()}>
              <FileJson />
              {messages.exportJson}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function ResumeDetailAccountActions({
  locale,
  messages,
  model,
  onLocaleChange,
}: {
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  onLocaleChange: (locale: Locale) => void;
}) {
  const { commands, state } = model;

  return (
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
          commands.changeTheme(
            state.resolvedTheme === "dark" ? "light" : "dark",
          )
        }
      >
        {state.resolvedTheme === "dark" ? (
          <Sun className="size-4" />
        ) : (
          <Moon className="size-4" />
        )}
      </Button>
      <Button type="button" variant="outline" onClick={commands.logout}>
        <LogOut className="size-4" />
        {messages.logout}
      </Button>
    </div>
  );
}

export function ResumeDetailWorkspaceHeader({
  headerRef,
  locale,
  messages,
  model,
  onLocaleChange,
}: {
  headerRef: RefObject<HTMLElement | null>;
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  onLocaleChange: (locale: Locale) => void;
}) {
  const { commands, state } = model;
  const toolbarTitle = state.resumeItem?.title || messages.untitledResume;

  return (
    <header
      ref={headerRef}
      className="sticky top-0 z-20 grid min-h-16 grid-cols-[auto_minmax(0,1fr)] items-center gap-3 border-b border-border bg-background px-4 py-2 print:hidden"
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
          onClick={commands.back}
        >
          <ChevronLeft className="size-4" />
          {messages.backToResumes}
        </Button>
        {!state.hasLoadError ? (
          <div className="flex min-w-0 items-center gap-1">
            <h1
              className="max-w-36 truncate text-sm font-medium text-foreground"
              title={toolbarTitle}
            >
              {formatResumeTitleForToolbar(toolbarTitle)}
            </h1>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label={messages.editResumeTitle}
              onClick={() => commands.setTitleDialogOpen(true)}
            >
              <Pencil className="size-3.5 text-muted-foreground" />
            </Button>
          </div>
        ) : (
          <h1 className="text-sm font-medium text-foreground">
            {messages.myResume}
          </h1>
        )}
      </div>

      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
        {!state.hasLoadError ? (
          <ResumeDetailEditorActions
            locale={locale}
            messages={messages}
            model={model}
          />
        ) : null}
        <ResumeDetailAccountActions
          locale={locale}
          messages={messages}
          model={model}
          onLocaleChange={onLocaleChange}
        />
      </div>
    </header>
  );
}
