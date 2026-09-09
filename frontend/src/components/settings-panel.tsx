import { Settings2, Sparkles } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { AgentSettingsTab } from "@/components/agent-settings-tab";
import type { SettingsPanelProps } from "@/components/settings-panel-types";
import { SiteSettingsTab } from "@/components/site-settings-tab";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

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
    <div className="flex flex-1 items-start p-4 sm:p-6 lg:p-8">
      <Tabs
        value={activeTab}
        onValueChange={changeTab}
        className="mx-auto w-full max-w-6xl gap-0"
      >
        <TabsList aria-label={t.settings} className="relative grid grid-cols-2">
          <span
            aria-hidden="true"
            className={cn(
              "pointer-events-none absolute inset-y-[3.5px] left-[3px] w-[calc(50%_-_3px)] rounded-md border border-transparent bg-background shadow-sm transition-transform duration-200 ease-out motion-reduce:transition-none dark:border-input dark:bg-input/30",
              activeTab === "agent" && "translate-x-full",
            )}
          />
          <TabsTrigger
            value="site"
            className="data-[state=active]:border-transparent! data-[state=active]:bg-transparent! data-[state=active]:shadow-none!"
          >
            <Settings2 />
            {t.siteSettingsTitle}
          </TabsTrigger>
          <TabsTrigger
            value="agent"
            className="data-[state=active]:border-transparent! data-[state=active]:bg-transparent! data-[state=active]:shadow-none!"
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
    </div>
  );
}
