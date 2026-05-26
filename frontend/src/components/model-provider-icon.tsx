import { cn } from "@/lib/utils";
import { useEffect, useState, type ComponentType } from "react";

const LOBE_PROVIDER_ALIASES: Record<string, string> = {
  "amazon-bedrock": "bedrock",
  "cloudflare-workers-ai": "cloudflare",
  "fireworks-ai": "fireworksai",
  "google-vertex": "google",
  "google-vertex-anthropic": "anthropic",
  moonshotai: "moonshot",
  zhipuai: "zhipu",
};

type LobeProviderIconProps = {
  className?: string;
  provider: string;
  size?: number;
  type?: "mono" | "color" | "avatar";
};

let providerIconPromise: Promise<ComponentType<LobeProviderIconProps> | null> | null =
  null;
let cachedProviderIcon: ComponentType<LobeProviderIconProps> | null = null;
let providerIconLoadFailed = false;

const loadProviderIcon = () => {
  if (cachedProviderIcon || providerIconLoadFailed) {
    return Promise.resolve(cachedProviderIcon);
  }

  providerIconPromise ??= import("@lobehub/icons")
    .then((module) => {
      cachedProviderIcon =
        module.ProviderIcon as ComponentType<LobeProviderIconProps>;
      return cachedProviderIcon;
    })
    .catch(() => {
      providerIconLoadFailed = true;
      return null;
    });

  return providerIconPromise;
};

export function ModelProviderIcon({
  provider,
  className,
  size = 20,
  type = "color",
}: {
  provider: string;
  className?: string;
  size?: number;
  type?: "mono" | "color" | "avatar";
}) {
  const [LoadedProviderIcon, setLoadedProviderIcon] =
    useState<ComponentType<LobeProviderIconProps> | null>(null);

  useEffect(() => {
    let mounted = true;

    loadProviderIcon()
      .then((component) => {
        if (mounted && component) {
          setLoadedProviderIcon(() => component);
        }
      });

    return () => {
      mounted = false;
    };
  }, []);

  if (provider === "sglang") {
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

  if (!LoadedProviderIcon) {
    return (
      <span
        aria-hidden="true"
        className={cn("inline-block shrink-0", className)}
        style={{ height: size, width: size }}
      />
    );
  }

  return (
    <LoadedProviderIcon
      className={cn("shrink-0 text-foreground", className)}
      provider={LOBE_PROVIDER_ALIASES[provider] ?? provider}
      size={size}
      type={type}
    />
  );
}
