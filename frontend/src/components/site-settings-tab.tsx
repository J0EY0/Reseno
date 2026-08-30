import {
  KeyRound,
  Languages,
  Monitor,
  Moon,
  Sun,
} from "lucide-react";

import { PasswordSettingsDialog } from "@/components/password-settings-dialog";
import {
  OptionToggleGroup,
  SettingsRow,
  SettingsSection,
} from "@/components/settings-controls";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { TabsContent } from "@/components/ui/tabs";
import { usePasswordSettings } from "@/components/use-password-settings";
import type { AppMessages, Locale } from "@/i18n";
import type { ThemeMode } from "@/types/resume";

export function SiteSettingsTab({
  locale,
  t,
  theme,
  onThemeChange,
  onLocaleChange,
  onPasswordChanged,
}: {
  locale: Locale;
  t: AppMessages;
  theme: ThemeMode;
  onThemeChange: (value: ThemeMode) => void;
  onLocaleChange: (value: Locale) => void;
  onPasswordChanged: () => void;
}) {
  // This owner stays mounted when Radix unmounts inactive tab content, matching
  // the original behavior where password dialog state lived above TabsContent.
  const passwordController = usePasswordSettings({ t, onPasswordChanged });
  const themeItems: Array<{
    value: ThemeMode;
    label: string;
    icon: React.ReactNode;
  }> = [
    { value: "light", label: t.light, icon: <Sun /> },
    { value: "dark", label: t.dark, icon: <Moon /> },
    { value: "system", label: t.systemTheme, icon: <Monitor /> },
  ];

  return (
    <TabsContent value="site" className="mt-5 flex flex-col gap-6">
      <SettingsSection title={t.preferencesSettingsTitle}>
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
            <SelectTrigger
              aria-label={t.language}
              className="ml-auto w-28 max-w-full"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end" position="popper" sideOffset={4}>
              <SelectGroup>
                <SelectItem value="zh">{t.languageChinese}</SelectItem>
                <SelectItem value="en">{t.languageEnglish}</SelectItem>
              </SelectGroup>
            </SelectContent>
          </Select>
        </SettingsRow>
        <Separator className="mx-5 w-auto sm:mx-6" />

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

      <SettingsSection title={t.accountSecuritySettingsTitle}>
        <SettingsRow
          icon={<KeyRound />}
          label={t.passwordSettingsTitle}
          description={t.passwordSettingsDescription}
        >
          <div className="flex justify-end">
            <PasswordSettingsDialog
              t={t}
              controller={passwordController}
            />
          </div>
        </SettingsRow>
      </SettingsSection>
    </TabsContent>
  );
}
