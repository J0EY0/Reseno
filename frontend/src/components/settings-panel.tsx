import {
  Globe,
  Bot,
  Moon,
  Monitor,
  Sun,
  KeyRound,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import type { AppMessages, Locale } from "@/i18n";
import {
  validatePasswordUpdateForm,
  type PasswordUpdateFormErrors,
} from "@/lib/auth-validation";
import { updateAuthPassword } from "@/lib/auth";
import { cn } from "@/lib/utils";
import type {
  AgentBehaviorMode,
  AgentConfirmationMode,
  AgentResponseLanguage,
  AgentSettings,
  ModelConfig,
  ThemeMode,
} from "@/types/resume";
import { getModelProviderMeta } from "@/lib/model-providers";

import { PasswordField } from "@/components/auth/password-field";
import { ModelProviderIcon } from "@/components/model-provider-icon";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
function ToggleRow({
  label,
  description,
  children,
}: {
  label: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col justify-between gap-3 rounded-xl border border-border/70 bg-muted/30 p-4 md:flex-row md:items-center">
      <div className="space-y-1">
        <p className="font-medium text-foreground">{label}</p>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function ButtonTabs<T extends string>({
  items,
  value,
  onChange,
}: {
  items: Array<{ value: T; label: string; icon?: ReactNode }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="inline-flex flex-wrap items-center gap-1 rounded-lg border border-border bg-card p-1">
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onChange(item.value)}
          className={cn(
            "inline-flex min-w-20 items-center justify-center gap-1.5 rounded-md px-3 py-2 text-sm transition-colors",
            value === item.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
          )}
        >
          {item.icon}
          <span>{item.label}</span>
        </button>
      ))}
    </div>
  );
}

export function SettingsPanel({
  locale,
  t,
  theme,
  onThemeChange,
  onLocaleChange,
  agentSettings,
  onAgentSettingsChange,
  modelConfigs,
  onPasswordChanged,
}: {
  locale: Locale;
  t: AppMessages;
  theme: ThemeMode;
  onThemeChange: (value: ThemeMode) => void;
  onLocaleChange: (value: Locale) => void;
  agentSettings: AgentSettings;
  onAgentSettingsChange: (value: AgentSettings) => void;
  modelConfigs: ModelConfig[];
  onPasswordChanged: () => void;
}) {
  const [activeTab, setActiveTab] = useState<"site" | "agent">("site");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordFormErrors, setPasswordFormErrors] =
    useState<PasswordUpdateFormErrors>({});
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [isPasswordSubmitting, setIsPasswordSubmitting] = useState(false);
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] = useState(false);
  const languageItems: Array<{ value: Locale; label: string }> = [
    { value: "zh", label: "中文" },
    { value: "en", label: "EN" },
  ];

  const themeItems: Array<{
    value: ThemeMode;
    label: string;
    icon: React.ReactNode;
  }> = [
    { value: "light", label: t.light, icon: <Sun className="size-4" /> },
    { value: "dark", label: t.dark, icon: <Moon className="size-4" /> },
    { value: "system", label: t.systemTheme, icon: <Monitor className="size-4" /> },
  ];

  const behaviorItems: Array<{ value: AgentBehaviorMode; label: string }> = [
    { value: "balanced", label: t.agentBehaviorBalanced },
    { value: "strict", label: t.agentBehaviorStrict },
    { value: "aggressive", label: t.agentBehaviorAggressive },
  ];
  const confirmationItems: Array<{
    value: AgentConfirmationMode;
    label: string;
  }> = [
    { value: "always", label: t.agentConfirmationAlways },
    { value: "lowRiskAuto", label: t.agentConfirmationLowRiskAuto },
    { value: "suggestOnly", label: t.agentConfirmationSuggestOnly },
  ];

  const responseLanguageItems: Array<{
    value: AgentResponseLanguage;
    label: string;
  }> = [
    { value: "follow", label: t.followSystemLanguage },
    { value: "zh", label: "中文" },
    { value: "en", label: "EN" },
  ];

  const isSiteTab = activeTab === "site";
  const selectedDefaultModel =
    modelConfigs.find((config) => config.id === agentSettings.defaultModelId) ??
    null;

  function renderModelOption(config: ModelConfig) {
    const provider = getModelProviderMeta(config.provider);
    const label =
      config.nickname.trim() || config.model.trim() || t.agentModelNotConfigured;

    return (
      <div className="flex min-w-0 items-center gap-2">
        <ModelProviderIcon provider={provider.iconProvider} size={18} />
        <span className="truncate">{label}</span>
      </div>
    );
  }

  function resetPasswordForm() {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setPasswordFormErrors({});
    setPasswordError(null);
  }

  function handlePasswordDialogOpenChange(open: boolean) {
    setIsPasswordDialogOpen(open);
    if (!open) {
      resetPasswordForm();
    }
  }

  async function handlePasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPasswordError(null);
    const nextErrors = validatePasswordUpdateForm(
      currentPassword,
      newPassword,
      confirmPassword,
      t,
    );

    if (Object.keys(nextErrors).length > 0) {
      setPasswordFormErrors(nextErrors);
      return;
    }

    setPasswordFormErrors({});
    setIsPasswordSubmitting(true);

    try {
      await updateAuthPassword({
        currentPassword,
        newPassword,
        confirmPassword,
      });
      setIsPasswordDialogOpen(false);
      resetPasswordForm();
      onPasswordChanged();
    } catch (error) {
      setPasswordError(
        error instanceof Error ? error.message : t.passwordUpdateFailed,
      );
    } finally {
      setIsPasswordSubmitting(false);
    }
  }

  return (
    <main className="grid flex-1 gap-4 p-4">
      <Card className="rounded-2xl border-border/80">
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-2xl border border-border bg-muted">
              {isSiteTab ? (
                <Globe className="size-4" />
              ) : (
                <Bot className="size-4" />
              )}
            </div>
            <div>
              <CardTitle>
                {isSiteTab ? t.siteSettingsTitle : t.agentSettingsTitle}
              </CardTitle>
              <CardDescription className="mt-1">
                {isSiteTab ? t.siteSettingsHint : t.agentSettingsHint}
              </CardDescription>
            </div>
          </div>
          <div className="pt-2">
            <ButtonTabs
              items={[
                {
                  value: "site",
                  label: t.siteSettingsTitle,
                  icon: <Globe className="size-4" />,
                },
                {
                  value: "agent",
                  label: t.agentSettingsTitle,
                  icon: <Bot className="size-4" />,
                },
              ]}
              value={activeTab}
              onChange={setActiveTab}
            />
          </div>
        </CardHeader>
        <CardContent className="grid gap-4">
          {isSiteTab ? (
            <>
              <ToggleRow label={t.language} description={t.siteLanguageHint}>
                <ButtonTabs
                  items={languageItems}
                  value={locale}
                  onChange={onLocaleChange}
                />
              </ToggleRow>

              <ToggleRow label={t.theme} description={t.siteThemeHint}>
                <ButtonTabs
                  items={themeItems}
                  value={theme}
                  onChange={onThemeChange}
                />
              </ToggleRow>

              <ToggleRow
                label={t.passwordSettingsTitle}
                description={t.passwordSettingsHint}
              >
                <Dialog
                  open={isPasswordDialogOpen}
                  onOpenChange={handlePasswordDialogOpenChange}
                >
                  <DialogTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="gap-1.5 bg-card px-3"
                    >
                      <KeyRound className="size-4 text-muted-foreground" />
                      {t.updatePassword}
                    </Button>
                  </DialogTrigger>
                  <DialogContent
                    showCloseButton
                    className="w-[min(420px,calc(100vw-2rem))]"
                  >
                    <form className="grid gap-4" onSubmit={handlePasswordSubmit}>
                      <DialogHeader>
                        <DialogTitle>{t.passwordSettingsTitle}</DialogTitle>
                      </DialogHeader>
                      <div className="grid gap-3">
                        <PasswordField
                          id="current-password"
                          label={t.currentPassword}
                          autoComplete="current-password"
                          value={currentPassword}
                          placeholder={t.currentPassword}
                          error={passwordFormErrors.currentPassword}
                          showPasswordLabel={t.loginShowPassword}
                          hidePasswordLabel={t.loginHidePassword}
                          onChange={(value) => {
                            setCurrentPassword(value);
                            setPasswordFormErrors((current) => ({
                              ...current,
                              currentPassword: undefined,
                            }));
                          }}
                        />
                        <PasswordField
                          id="new-password"
                          label={t.newPassword}
                          autoComplete="new-password"
                          value={newPassword}
                          placeholder={t.newPassword}
                          error={passwordFormErrors.newPassword}
                          showPasswordLabel={t.loginShowPassword}
                          hidePasswordLabel={t.loginHidePassword}
                          onChange={(value) => {
                            setNewPassword(value);
                            setPasswordFormErrors((current) => ({
                              ...current,
                              newPassword: undefined,
                              confirmPassword: undefined,
                            }));
                          }}
                        />
                        <PasswordField
                          id="confirm-password"
                          label={t.confirmPassword}
                          autoComplete="new-password"
                          value={confirmPassword}
                          placeholder={t.confirmPassword}
                          error={passwordFormErrors.confirmPassword}
                          showPasswordLabel={t.loginShowPassword}
                          hidePasswordLabel={t.loginHidePassword}
                          onChange={(value) => {
                            setConfirmPassword(value);
                            setPasswordFormErrors((current) => ({
                              ...current,
                              confirmPassword: undefined,
                            }));
                          }}
                        />
                        {passwordError ? (
                          <p className="text-sm text-destructive">
                            {passwordError}
                          </p>
                        ) : null}
                      </div>
                      <DialogFooter>
                        <DialogClose asChild>
                          <Button
                            type="button"
                            variant="outline"
                            disabled={isPasswordSubmitting}
                          >
                            {t.cancel}
                          </Button>
                        </DialogClose>
                        <Button
                          type="submit"
                          disabled={isPasswordSubmitting}
                        >
                          {isPasswordSubmitting
                            ? t.passwordUpdating
                            : t.updatePassword}
                        </Button>
                      </DialogFooter>
                    </form>
                  </DialogContent>
                </Dialog>
              </ToggleRow>
            </>
          ) : (
            <>
              <ToggleRow
                label={t.defaultAgentModel}
                description={t.defaultAgentModelHint}
              >
                <Select
                  value={selectedDefaultModel?.id}
                  disabled={modelConfigs.length === 0}
                  onValueChange={(value) =>
                    onAgentSettingsChange({
                      ...agentSettings,
                      defaultModelId: value,
                    })
                  }
                >
                  <SelectTrigger className="min-w-[280px] bg-card">
                    <SelectValue placeholder={t.agentModelNotConfigured}>
                      {selectedDefaultModel
                        ? renderModelOption(selectedDefaultModel)
                        : t.agentModelNotConfigured}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent className="min-w-[280px]">
                    <SelectGroup>
                      {modelConfigs.map((config) => (
                        <SelectItem key={config.id} value={config.id}>
                          {renderModelOption(config)}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </ToggleRow>

              <ToggleRow
                label={t.agentResponseLanguage}
                description={t.agentResponseLanguageHint}
              >
                <ButtonTabs
                  items={responseLanguageItems}
                  value={agentSettings.responseLanguage}
                  onChange={(value) =>
                    onAgentSettingsChange({
                      ...agentSettings,
                      responseLanguage: value,
                    })
                  }
                />
              </ToggleRow>

              <ToggleRow
                label={t.agentBehavior}
                description={t.agentBehaviorHint}
              >
                <ButtonTabs
                  items={behaviorItems}
                  value={agentSettings.behaviorMode}
                  onChange={(value) =>
                    onAgentSettingsChange({
                      ...agentSettings,
                      behaviorMode: value,
                    })
                  }
                />
              </ToggleRow>

              <ToggleRow
                label={t.agentConfirmationMode}
                description={t.agentConfirmationModeHint}
              >
                <ButtonTabs
                  items={confirmationItems}
                  value={agentSettings.confirmationMode}
                  onChange={(value) =>
                    onAgentSettingsChange({
                      ...agentSettings,
                      confirmationMode: value,
                    })
                  }
                />
              </ToggleRow>
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
