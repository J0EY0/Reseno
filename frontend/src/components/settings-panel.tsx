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

import { PasswordField } from "@/components/auth/password-field";
import { ModelProviderIcon } from "@/components/model-provider-icon";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
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
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldGroup,
  FieldSeparator,
  FieldTitle,
} from "@/components/ui/field";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ToggleGroup,
  ToggleGroupItem,
} from "@/components/ui/toggle-group";

function SettingsRow({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Field
      className={cn(
        "min-h-16 gap-3 px-5 py-4 @2xl/field-group:grid @2xl/field-group:grid-cols-[minmax(0,1fr)_20rem] @2xl/field-group:items-center @2xl/field-group:gap-6",
        description && "min-h-[76px]",
      )}
    >
      <FieldContent className="gap-1">
        <FieldTitle>{label}</FieldTitle>
        {description ? (
          <FieldDescription>{description}</FieldDescription>
        ) : null}
      </FieldContent>
      <div className="w-full">{children}</div>
    </Field>
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
          className="min-w-0 flex-auto shrink px-2"
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
    { value: "zh", label: t.languageChinese },
    { value: "en", label: t.languageEnglish },
  ];

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
    <main className="flex flex-1 items-start p-4">
      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as "site" | "agent")}
        className="w-full gap-0"
      >
        <Card className="w-full gap-0 overflow-hidden rounded-[26px] border-border py-4 shadow-none">
          <CardHeader className="mx-4 gap-0 border-b border-border/70 px-0 py-0 pb-0!">
            <TabsList
              variant="line"
              className="w-full justify-start gap-6 p-0 group-data-[orientation=horizontal]/tabs:h-9"
            >
              <TabsTrigger
                value="site"
                className="h-9 flex-none rounded-none border-transparent px-1 py-0 after:bottom-[-1px]! focus-visible:border-transparent focus-visible:outline-none focus-visible:ring-0"
              >
                <Globe />
                {t.siteSettingsTitle}
              </TabsTrigger>
              <TabsTrigger
                value="agent"
                className="h-9 flex-none rounded-none border-transparent px-1 py-0 after:bottom-[-1px]! focus-visible:border-transparent focus-visible:outline-none focus-visible:ring-0"
              >
                <Bot />
                {t.agentSettingsTitle}
              </TabsTrigger>
            </TabsList>
          </CardHeader>
          <CardContent className="p-0">
            <TabsContent value="site" className="m-0">
              <FieldGroup className="gap-0">
                <SettingsRow label={t.language}>
                  <OptionToggleGroup
                    items={languageItems}
                    value={locale}
                    onChange={onLocaleChange}
                  />
                </SettingsRow>
                <FieldSeparator className="m-0 h-px" />

                <SettingsRow label={t.theme}>
                  <OptionToggleGroup
                    items={themeItems}
                    value={theme}
                    onChange={onThemeChange}
                  />
                </SettingsRow>
                <FieldSeparator className="m-0 h-px" />

                <SettingsRow label={t.passwordSettingsTitle}>
                  <div className="flex justify-end">
                    <Dialog
                      open={isPasswordDialogOpen}
                      onOpenChange={handlePasswordDialogOpenChange}
                    >
                      <DialogTrigger asChild>
                        <Button type="button" variant="outline">
                          <KeyRound data-icon="inline-start" />
                          {t.updatePassword}
                        </Button>
                      </DialogTrigger>
                      <DialogContent
                        showCloseButton
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
              </FieldGroup>
            </TabsContent>

            <TabsContent value="agent" className="m-0">
              <FieldGroup className="gap-0">
                <SettingsRow
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
                    <SelectTrigger className="w-full">
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
                <FieldSeparator className="m-0 h-px" />

                <SettingsRow
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
                <FieldSeparator className="m-0 h-px" />

                <SettingsRow
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
                <FieldSeparator className="m-0 h-px" />

                <SettingsRow
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
              </FieldGroup>
            </TabsContent>
          </CardContent>
        </Card>
      </Tabs>
    </main>
  );
}
