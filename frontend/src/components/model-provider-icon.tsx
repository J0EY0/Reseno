import Anthropic from "@lobehub/icons/es/Anthropic/components/Mono";
import DeepSeekColor from "@lobehub/icons/es/DeepSeek/components/Color";
import GoogleColor from "@lobehub/icons/es/Google/components/Color";
import MinimaxColor from "@lobehub/icons/es/Minimax/components/Color";
import Moonshot from "@lobehub/icons/es/Moonshot/components/Mono";
import Ollama from "@lobehub/icons/es/Ollama/components/Mono";
import OpenAI from "@lobehub/icons/es/OpenAI/components/Mono";
import QwenColor from "@lobehub/icons/es/Qwen/components/Color";
import VllmColor from "@lobehub/icons/es/Vllm/components/Color";
import XAI from "@lobehub/icons/es/XAI/components/Mono";
import ZAI from "@lobehub/icons/es/ZAI/components/Mono";
import { Bot } from "lucide-react";

import { cn } from "@/lib/utils";

const PROVIDER_ALIASES: Record<string, string> = {
  "custom-cloud": "openai",
  glm: "zai",
  "google-vertex": "google",
  "google-vertex-anthropic": "anthropic",
  moonshotai: "moonshot",
  zhipu: "zai",
  zhipuai: "zai",
};

// Keep this registry finite so adding one provider never pulls the package-wide
// ProviderIcon registry (and every icon it references) into the application.
const PROVIDER_ICONS = {
  anthropic: { mono: Anthropic },
  deepseek: { color: DeepSeekColor },
  google: { color: GoogleColor },
  minimax: { color: MinimaxColor },
  moonshot: { mono: Moonshot },
  ollama: { mono: Ollama },
  openai: { mono: OpenAI },
  qwen: { color: QwenColor },
  vllm: { color: VllmColor },
  xai: { mono: XAI },
  zai: { mono: ZAI },
} as const;

type ProviderIconId = keyof typeof PROVIDER_ICONS;

const hasProviderIcon = (provider: string): provider is ProviderIconId =>
  Object.hasOwn(PROVIDER_ICONS, provider);

export function ModelProviderIcon({
  provider,
  className,
  size = 20,
}: {
  provider: string;
  className?: string;
  size?: number;
}) {
  const normalizedProvider = PROVIDER_ALIASES[provider] ?? provider;

  if (normalizedProvider === "sglang") {
    return (
      <span
        aria-label="SGLang"
        className={cn(
          "inline-flex shrink-0 items-center justify-center font-semibold leading-none text-foreground",
          className,
        )}
        style={{ fontSize: Math.max(10, Math.round(size * 0.48)) }}
      >
        SG
      </span>
    );
  }

  if (!hasProviderIcon(normalizedProvider)) {
    return (
      <Bot
        aria-hidden="true"
        className={cn("shrink-0 text-muted-foreground", className)}
        size={size}
      />
    );
  }

  const icon = PROVIDER_ICONS[normalizedProvider];
  if ("color" in icon) {
    const ColorIcon = icon.color;
    return <ColorIcon className={cn("shrink-0", className)} size={size} />;
  }

  const ProviderIcon = icon.mono;

  return (
    <ProviderIcon
      className={cn("shrink-0 text-foreground", className)}
      size={size}
    />
  );
}
