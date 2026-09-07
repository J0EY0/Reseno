import { Ellipsis, Languages, LogOut, Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { AppMessages, Locale } from "@/i18n";

export function WorkspaceMobileActionsMenu({
  children,
  locale,
  messages,
  onLocaleChange,
  onLogout,
  onThemeChange,
  resolvedTheme,
}: {
  children?: ReactNode;
  locale: Locale;
  messages: AppMessages;
  onLocaleChange: (locale: Locale) => void;
  onLogout: () => void;
  onThemeChange: (theme: "light" | "dark") => void;
  resolvedTheme: "light" | "dark";
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={messages.actions}
          title={messages.actions}
        >
          <Ellipsis />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        {children ? (
          <>
            <DropdownMenuGroup>{children}</DropdownMenuGroup>
            <DropdownMenuSeparator />
          </>
        ) : null}

        <DropdownMenuLabel className="flex items-center gap-2 text-muted-foreground">
          <Languages />
          {messages.language}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={locale}
          onValueChange={(value) => {
            if (value === "zh" || value === "en") {
              onLocaleChange(value);
            }
          }}
        >
          <DropdownMenuRadioItem value="zh">
            {messages.uiLanguageChinese}
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="en">
            {messages.uiLanguageEnglish}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>

        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            onSelect={() =>
              onThemeChange(resolvedTheme === "dark" ? "light" : "dark")
            }
          >
            {resolvedTheme === "dark" ? <Sun /> : <Moon />}
            {messages.themeToggleLabel}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={onLogout}>
            <LogOut />
            {messages.logout}
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
