import {
  Bot,
  Gauge,
  KeyRound,
  Languages,
  Moon,
  Monitor,
  Palette,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
} from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import type { AppMessages, Locale } from "@/i18n";
import {
  validatePasswordUpdateForm,
  type PasswordUpdateFormErrors,
} from "@/lib/auth-validation";
import { updateAuthPassword } from "@/lib/auth";
import type {
  AgentBehaviorMode,
  AgentConfirmationMode,
  AgentResponseLanguage,
  AgentSettings,
  ModelConfig,
  ThemeMode,
} from "@/types/resume";

import { PasswordField } from "@/components/auth/password-field";
import { ModelProviderIcon } from "@/components/model-provider-icon";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
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
import { Spinner } from "@/components/ui/spinner";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group";

function SettingsRow({
  icon,
  label,
  description,
  children,
}: {
  icon: ReactNode;
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="grid min-h-20 gap-4 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)] sm:items-center sm:gap-6 sm:px-6"
    >
      <div className="flex min-w-0 items-start gap-3">
        <span
          className="mt-0.5 flex size-8 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-5"
          aria-hidden="true"
        >
          {icon}
        </span>
        <div className="min-w-0 space-y-0.5">
          <div className="text-sm font-medium text-foreground">{label}</div>
          {description ? (
            <p className="text-sm leading-5 text-muted-foreground">
              {description}
            </p>
          ) : null}
        </div>
      </div>
      <div className="w-full sm:justify-self-end">{children}</div>
    </div>
  );
}

function SettingsSection({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <Card className="gap-0 overflow-hidden rounded-xl py-0 shadow-xs">
      <CardHeader className="px-5 py-4 sm:px-6 sm:py-5">
        <CardTitle
          role="heading"
          aria-level={2}
          className="flex items-center gap-2.5 text-base"
        >
          <span
            className="flex size-7 items-center justify-center text-muted-foreground [&_svg]:size-[18px]"
            aria-hidden="true"
          >
            {icon}
          </span>
          {title}
        </CardTitle>
      </CardHeader>
      <Separator />
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  );
}

function OptionToggleGroup<T extends string>({
  items,
  value,
  onChange,
}: {
  items: Array<{ value: T; label: string; icon?: ReactNode }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <ToggleGroup
      type="single"
      variant="outline"
      spacing={0}
      value={value}
      className="w-full"
      onValueChange={(nextValue) => {
        if (nextValue) {
          onChange(nextValue as T);
        }
      }}
    >
      {items.map((item) => (
        <ToggleGroupItem
          key={item.value}
          value={item.value}
          aria-label={item.label}
          className="min-w-0 flex-auto shrink px-2 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
        >
          {item.icon}
          <span className="min-w-0 truncate">{item.label}</span>
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
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
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") === "agent" ? "agent" : "site";
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordFormErrors, setPasswordFormErrors] =
    useState<PasswordUpdateFormErrors>({});
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [isPasswordSubmitting, setIsPasswordSubmitting] = useState(false);
  const [isPasswordDialogOpen, setIsPasswordDialogOpen] = useState(false);
  const themeItems: Array<{
    value: ThemeMode;
    label: string;
    icon: React.ReactNode;
  }> = [
    { value: "light", label: t.light, icon: <Sun /> },
    { value: "dark", label: t.dark, icon: <Moon /> },
    { value: "system", label: t.systemTheme, icon: <Monitor /> },
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
    { value: "suggestOnly", label: t.agentConfirmationSuggestOnly },
  ];

  const responseLanguageItems: Array<{
    value: AgentResponseLanguage;
    label: string;
  }> = [
    { value: "follow", label: t.followSystemLanguage },
    { value: "zh", label: t.languageChinese },
    { value: "en", label: t.languageEnglish },
  ];

  const selectedDefaultModel =
    modelConfigs.find((config) => config.id === agentSettings.defaultModelId) ??
    null;

  function renderModelOption(config: ModelConfig) {
    const label =
      config.nickname.trim() || config.model.trim() || t.agentModelNotConfigured;

    return (
      <div className="flex min-w-0 items-center gap-2">
        <ModelProviderIcon
          provider={config.iconProvider || config.provider}
          size={18}
        />
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
    <main className="flex flex-1 items-start p-4 sm:p-6 lg:p-8">
      <Tabs
        value={activeTab}
        onValueChange={(value) => {
          setSearchParams((current) => {
            const next = new URLSearchParams(current);

            if (value === "agent") {
              next.set("tab", "agent");
            } else {
              next.delete("tab");
            }

            return next;
          });
        }}
        className="mx-auto w-full max-w-6xl gap-0"
      >
        <TabsList
          aria-label={t.settings}
          className="h-auto w-full justify-start gap-2 bg-transparent p-0"
        >
          <TabsTrigger
            value="site"
            className="h-10 flex-none rounded-lg border border-transparent px-4 data-[state=active]:border-border data-[state=active]:bg-accent data-[state=active]:shadow-none"
          >
            <Settings2 />
            {t.siteSettingsTitle}
          </TabsTrigger>
          <TabsTrigger
            value="agent"
            className="h-10 flex-none rounded-lg border border-transparent px-4 data-[state=active]:border-border data-[state=active]:bg-accent data-[state=active]:shadow-none"
          >
            <Sparkles />
            {t.agentSettingsTitle}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="site" className="mt-5 space-y-5">
          <SettingsSection icon={<SlidersHorizontal />} title={t.generalSettingsTitle}>
            <SettingsRow
              icon={<Languages />}
              label={t.language}
              description={t.languageSettingsDescription}
            >
              <Select
                value={locale}
                onValueChange={(value) => {
                  if (value === "zh" || value === "en") {
                    onLocaleChange(value);
                  }
                }}
              >
                <SelectTrigger aria-label={t.language} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end">
                  <SelectGroup>
                    <SelectItem value="zh">{t.languageChinese}</SelectItem>
                    <SelectItem value="en">{t.languageEnglish}</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </SettingsRow>
          </SettingsSection>

          <SettingsSection icon={<Palette />} title={t.appearanceSettingsTitle}>
            <SettingsRow
              icon={<Moon />}
              label={t.theme}
              description={t.themeSettingsDescription}
            >
              <OptionToggleGroup
                items={themeItems}
                value={theme}
                onChange={onThemeChange}
              />
            </SettingsRow>
          </SettingsSection>

          <SettingsSection icon={<ShieldCheck />} title={t.accountSecuritySettingsTitle}>
            <SettingsRow
              icon={<KeyRound />}
              label={t.passwordSettingsTitle}
              description={t.passwordSettingsDescription}
            >
              <div className="flex justify-end">
                <Dialog
                  open={isPasswordDialogOpen}
                  onOpenChange={handlePasswordDialogOpenChange}
                >
                  <DialogTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full sm:w-auto"
                    >
                      {t.updatePassword}
                    </Button>
                  </DialogTrigger>
                  <DialogContent
                    showCloseButton
                    closeLabel={t.close}
                    aria-describedby={undefined}
                    className="w-[min(420px,calc(100vw-2rem))]"
                  >
                    <form
                      className="grid gap-4"
                      onSubmit={handlePasswordSubmit}
                    >
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
                          {isPasswordSubmitting ? (
                            <Spinner
                              data-icon="inline-start"
                              aria-label={t.passwordUpdating}
                            />
                          ) : null}
                          {isPasswordSubmitting
                            ? t.passwordUpdating
                            : t.updatePassword}
                        </Button>
                      </DialogFooter>
                    </form>
                  </DialogContent>
                </Dialog>
              </div>
            </SettingsRow>
          </SettingsSection>
        </TabsContent>

        <TabsContent value="agent" className="mt-5 space-y-5">
          <SettingsSection icon={<Bot />} title={t.agentModelSettingsTitle}>
            <SettingsRow
              icon={<Bot />}
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
                <SelectTrigger
                  aria-label={t.defaultAgentModel}
                  className="w-full"
                >
                  <SelectValue placeholder={t.agentModelNotConfigured}>
                    {selectedDefaultModel
                      ? renderModelOption(selectedDefaultModel)
                      : t.agentModelNotConfigured}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent className="min-w-[20rem]">
                  <SelectGroup>
                    {modelConfigs.map((config) => (
                      <SelectItem key={config.id} value={config.id}>
                        {renderModelOption(config)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </SettingsRow>
          </SettingsSection>

          <SettingsSection
            icon={<SlidersHorizontal />}
            title={t.agentInteractionSettingsTitle}
          >
            <SettingsRow
              icon={<Languages />}
              label={t.agentResponseLanguage}
              description={t.agentResponseLanguageHint}
            >
              <OptionToggleGroup
                items={responseLanguageItems}
                value={agentSettings.responseLanguage}
                onChange={(value) =>
                  onAgentSettingsChange({
                    ...agentSettings,
                    responseLanguage: value,
                  })
                }
              />
            </SettingsRow>
            <Separator className="mx-5 w-auto sm:mx-6" />

            <SettingsRow
              icon={<Gauge />}
              label={t.agentBehavior}
              description={t.agentBehaviorHint}
            >
              <OptionToggleGroup
                items={behaviorItems}
                value={agentSettings.behaviorMode}
                onChange={(value) =>
                  onAgentSettingsChange({
                    ...agentSettings,
                    behaviorMode: value,
                  })
                }
              />
            </SettingsRow>
            <Separator className="mx-5 w-auto sm:mx-6" />

            <SettingsRow
              icon={<ShieldCheck />}
              label={t.agentConfirmationMode}
              description={t.agentConfirmationModeHint}
            >
              <OptionToggleGroup
                items={confirmationItems}
                value={agentSettings.confirmationMode}
                onChange={(value) =>
                  onAgentSettingsChange({
                    ...agentSettings,
                    confirmationMode: value,
                  })
                }
              />
            </SettingsRow>
          </SettingsSection>
        </TabsContent>
      </Tabs>
    </main>
  );
}
