import { Settings2, Sparkles } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { AgentSettingsTab } from "@/components/agent-settings-tab";
import type { SettingsPanelProps } from "@/components/settings-panel-types";
import { SiteSettingsTab } from "@/components/site-settings-tab";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

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
}: SettingsPanelProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") === "agent" ? "agent" : "site";

  function changeTab(value: string) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);

      if (value === "agent") {
        next.set("tab", "agent");
      } else {
        next.delete("tab");
      }

      return next;
    });
  }

  return (
    <main className="flex flex-1 items-start p-4 sm:p-6 lg:p-8">
      <Tabs
        value={activeTab}
        onValueChange={changeTab}
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

        <SiteSettingsTab
          locale={locale}
          t={t}
          theme={theme}
          onThemeChange={onThemeChange}
          onLocaleChange={onLocaleChange}
          onPasswordChanged={onPasswordChanged}
        />
        <AgentSettingsTab
          t={t}
          agentSettings={agentSettings}
          onAgentSettingsChange={onAgentSettingsChange}
          modelConfigs={modelConfigs}
        />
      </Tabs>
    </main>
  );
}
