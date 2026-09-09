import {
  ChevronDown,
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
  Sun,
} from "lucide-react";

import { ResumeFormatPopover } from "@/components/editor/resume-format-popover";
import { SaveStatusButton } from "@/components/save-status-button";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
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
import type { ResumeDetailWorkspaceModel } from "@/components/workspace/resume-detail-workspace-types";
import { WorkspaceMobileActionsMenu } from "@/components/workspace/workspace-mobile-actions-menu";
import type { AppMessages, Locale } from "@/i18n";

interface ResumeDetailHeaderActionsProps {
  compact: boolean;
  locale: Locale;
  messages: AppMessages;
  model: ResumeDetailWorkspaceModel;
  onLocaleChange: (locale: Locale) => void;
}

function ResumeDetailCompactActions({
  locale,
  messages,
  model,
  onLocaleChange,
}: Omit<ResumeDetailHeaderActionsProps, "compact">) {
  const { commands, state } = model;

  if (state.hasLoadError) {
    return (
      <WorkspaceMobileActionsMenu
        locale={locale}
        messages={messages}
        onLocaleChange={onLocaleChange}
        onLogout={commands.logout}
        onThemeChange={commands.changeTheme}
        resolvedTheme={state.resolvedTheme}
      />
    );
  }

  return (
    <div className="flex items-center gap-2">
      <ResumeFormatPopover
        compact
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

      <div
        className="relative"
        data-agent-draft={Boolean(state.agent.draft)}
        data-agent-status={state.agent.panelStatus ?? "idle"}
      >
        <WorkspaceMobileActionsMenu
          locale={locale}
          messages={messages}
          onLocaleChange={onLocaleChange}
          onLogout={commands.logout}
          onThemeChange={commands.changeTheme}
          resolvedTheme={state.resolvedTheme}
        >
          <DropdownMenuItem
            onSelect={() =>
              commands.agent.setPanelCollapsed(!state.agent.isPanelCollapsed)
            }
          >
            <ChevronRight />
            {state.agent.isPanelCollapsed
              ? messages.agentExpandPanel
              : messages.agentCollapsePanel}
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={
              state.document.isSmartFittingOnePage ||
              !state.document.isPreviewReady
            }
            onSelect={() => void commands.fitOnePage()}
          >
            {state.document.isSmartFittingOnePage ? (
              <Spinner aria-label={messages.smartOnePage} />
            ) : (
              <Minimize2 />
            )}
            {messages.smartOnePage}
          </DropdownMenuItem>
          <DropdownMenuItem
            disabled={
              state.isDuplicatingResume ||
              state.isLoading ||
              state.save.state === "saving"
            }
            onSelect={() => void commands.duplicateResume()}
          >
            {state.isDuplicatingResume ? <Spinner /> : <CopyPlus />}
            {messages.duplicateResume}
          </DropdownMenuItem>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger
              disabled={state.isExporting || state.isLoading}
            >
              {state.isExporting ? (
                <Spinner aria-label={messages.exporting} />
              ) : (
                <Download />
              )}
              {state.isExporting ? messages.exporting : messages.export}
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
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
            </DropdownMenuSubContent>
          </DropdownMenuSub>
        </WorkspaceMobileActionsMenu>
        <span
          aria-hidden="true"
          className="agent-compact-status-indicator"
          data-slot="agent-compact-status-indicator"
        />
      </div>
    </div>
  );
}

function ResumeDetailEditorActions({
  locale,
  messages,
  model,
}: Pick<ResumeDetailHeaderActionsProps, "locale" | "messages" | "model">) {
  const { commands, state } = model;

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <Button
        type="button"
        variant="outline"
        onClick={() => void commands.fitOnePage()}
        disabled={
          state.document.isSmartFittingOnePage || !state.document.isPreviewReady
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
            className="min-w-32"
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
              <ChevronDown data-icon="inline-end" className="opacity-50" />
            ) : null}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="w-[var(--radix-dropdown-menu-trigger-width)] min-w-[var(--radix-dropdown-menu-trigger-width)]"
        >
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
}: Omit<ResumeDetailHeaderActionsProps, "compact">) {
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
            <SelectItem value="zh">{messages.uiLanguageChinese}</SelectItem>
            <SelectItem value="en">{messages.uiLanguageEnglish}</SelectItem>
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
        {state.resolvedTheme === "dark" ? <Sun /> : <Moon />}
      </Button>
      <Button type="button" variant="outline" onClick={commands.logout}>
        <LogOut />
        {messages.logout}
      </Button>
    </div>
  );
}

export function ResumeDetailHeaderActions({
  compact,
  locale,
  messages,
  model,
  onLocaleChange,
}: ResumeDetailHeaderActionsProps) {
  if (compact) {
    return (
      <ResumeDetailCompactActions
        locale={locale}
        messages={messages}
        model={model}
        onLocaleChange={onLocaleChange}
      />
    );
  }

  return (
    <>
      {!model.state.hasLoadError ? (
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
    </>
  );
}
