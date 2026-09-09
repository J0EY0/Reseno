import Anthropic from "@lobehub/icons/es/Anthropic";
import DeepSeek from "@lobehub/icons/es/DeepSeek";
import Google from "@lobehub/icons/es/Google";
import Minimax from "@lobehub/icons/es/Minimax";
import Moonshot from "@lobehub/icons/es/Moonshot";
import Ollama from "@lobehub/icons/es/Ollama";
import OpenAI from "@lobehub/icons/es/OpenAI";
import Qwen from "@lobehub/icons/es/Qwen";
import Vllm from "@lobehub/icons/es/Vllm";
import XAI from "@lobehub/icons/es/XAI";
import ZAI from "@lobehub/icons/es/ZAI";
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
  anthropic: Anthropic,
  deepseek: DeepSeek,
  google: Google,
  minimax: Minimax,
  moonshot: Moonshot,
  ollama: Ollama,
  openai: OpenAI,
  qwen: Qwen,
  vllm: Vllm,
  xai: XAI,
  zai: ZAI,
} as const;

type ProviderIconId = keyof typeof PROVIDER_ICONS;
type ProviderIconType = "mono" | "color" | "avatar";

const hasProviderIcon = (provider: string): provider is ProviderIconId =>
  Object.hasOwn(PROVIDER_ICONS, provider);

export function ModelProviderIcon({
  provider,
  className,
  size = 20,
  type = "color",
}: {
  provider: string;
  className?: string;
  size?: number;
  type?: ProviderIconType;
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

  const ProviderIcon = PROVIDER_ICONS[normalizedProvider];

  if (type === "avatar") {
    const AvatarIcon = ProviderIcon.Avatar;
    return <AvatarIcon className={cn("shrink-0", className)} size={size} />;
  }

  if (type === "color" && "Color" in ProviderIcon) {
    const ColorIcon = ProviderIcon.Color;
    return <ColorIcon className={cn("shrink-0", className)} size={size} />;
  }

  return (
    <ProviderIcon
      className={cn("shrink-0 text-foreground", className)}
      size={size}
    />
  );
}
