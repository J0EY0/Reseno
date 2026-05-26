import {
  Globe,
  Bot,
  Check,
  Moon,
  Sun,
  Type,
  ALargeSmall,
  KeyRound,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import type { AppMessages, Locale } from "@/i18n";
import {
  validatePasswordUpdateForm,
  type PasswordUpdateFormErrors,
} from "@/lib/auth-validation";
import { updateAuthPassword } from "@/lib/auth";
import { getModelDisplayName } from "@/lib/model-config";
import { cn } from "@/lib/utils";
import type {
  AgentBehaviorMode,
  AgentResponseLanguage,
  AgentSettings,
  ModelConfig,
  ResumeFontFamily,
  ThemeMode,
} from "@/types/resume";

import { PasswordField } from "@/components/auth/password-field";
import { Badge } from "@/components/ui/badge";
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

const fontSizeOptions = [12, 14, 16, 18, 20] as const;

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
  fontFamily,
  onFontFamilyChange,
  fontSize,
  onFontSizeChange,
  agentSettings,
  onAgentSettingsChange,
  modelConfigs,
  onOpenModelConfigs,
  onPasswordChanged,
}: {
  locale: Locale;
  t: AppMessages;
  theme: ThemeMode;
  onThemeChange: (value: ThemeMode) => void;
  onLocaleChange: (value: Locale) => void;
  fontFamily: ResumeFontFamily;
  onFontFamilyChange: (value: ResumeFontFamily) => void;
  fontSize: number;
  onFontSizeChange: (value: number) => void;
  agentSettings: AgentSettings;
  onAgentSettingsChange: (value: AgentSettings) => void;
  modelConfigs: ModelConfig[];
  onOpenModelConfigs: () => void;
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
  ];

  const behaviorItems: Array<{ value: AgentBehaviorMode; label: string }> = [
    { value: "balanced", label: t.agentBehaviorBalanced },
    { value: "strict", label: t.agentBehaviorStrict },
    { value: "aggressive", label: t.agentBehaviorAggressive },
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

              <ToggleRow label={t.fontFamily} description={t.siteFontHint}>
                <Select
                  value={fontFamily}
                  onValueChange={(value) =>
                    onFontFamilyChange(value as ResumeFontFamily)
                  }
                >
                  <SelectTrigger className="min-w-[180px] gap-2 bg-card">
                    <div className="flex min-w-0 items-center gap-2">
                      <Type className="size-4 text-muted-foreground" />
                      <SelectValue />
                    </div>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="inter">{t.fontInter}</SelectItem>
                    <SelectItem value="serif">{t.fontSerif}</SelectItem>
                    <SelectItem value="plex">{t.fontPlex}</SelectItem>
                  </SelectContent>
                </Select>
              </ToggleRow>

              <ToggleRow label={t.fontSize} description={t.siteFontSizeHint}>
                <Select
                  value={String(fontSize)}
                  onValueChange={(value) => onFontSizeChange(Number(value))}
                >
                  <SelectTrigger className="min-w-[140px] gap-2 bg-card">
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
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">{`${modelConfigs.length} ${t.configuredModels}`}</Badge>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={onOpenModelConfigs}
                >
                  {t.openModelSettings}
                </Button>
              </div>

              <ToggleRow
                label={t.defaultAgentModel}
                description={t.defaultAgentModelHint}
              >
                <Select
                  value={agentSettings.defaultModelId}
                  onValueChange={(value) =>
                    onAgentSettingsChange({
                      ...agentSettings,
                      defaultModelId: value,
                    })
                  }
                >
                  <SelectTrigger className="min-w-[220px] bg-card">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {modelConfigs.map((config) => (
                      <SelectItem key={config.id} value={config.id}>
                        {getModelDisplayName(config)}
                      </SelectItem>
                    ))}
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
                label={t.autoRunMatch}
                description={t.autoRunMatchHint}
              >
                <Button
                  type="button"
                  variant={agentSettings.autoRunMatch ? "default" : "outline"}
                  className="gap-2"
                  onClick={() =>
                    onAgentSettingsChange({
                      ...agentSettings,
                      autoRunMatch: !agentSettings.autoRunMatch,
                    })
                  }
                >
                  {agentSettings.autoRunMatch ? (
                    <Check className="size-4" />
                  ) : null}
                  {agentSettings.autoRunMatch ? t.enabled : t.disabled}
                </Button>
              </ToggleRow>
            </>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
