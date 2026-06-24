import { cn } from "@/lib/utils";
import { useEffect, useState, type ComponentType } from "react";

const LOBE_PROVIDER_ALIASES: Record<string, string> = {
  "amazon-bedrock": "bedrock",
  "cloudflare-workers-ai": "cloudflare",
  "google-vertex": "google",
  "google-vertex-anthropic": "anthropic",
  moonshotai: "moonshot",
};

const ZAI_PROVIDER_IDS = new Set(["glm", "zai", "zhipu", "zhipuai"]);

type LobeProviderIconProps = {
  className?: string;
  provider: string;
  size?: number;
  type?: "mono" | "color" | "avatar";
};

type LobeIconProps = Omit<LobeProviderIconProps, "provider">;
type LobeCompoundIcon = ComponentType<LobeIconProps> & {
  Avatar?: ComponentType<LobeIconProps>;
  Color?: ComponentType<LobeIconProps>;
};

let providerIconPromise: Promise<ComponentType<LobeProviderIconProps> | null> | null =
  null;
let cachedProviderIcon: ComponentType<LobeProviderIconProps> | null = null;
let providerIconLoadFailed = false;
let qwenIconPromise: Promise<LobeCompoundIcon | null> | null = null;
let cachedQwenIcon: LobeCompoundIcon | null = null;
let qwenIconLoadFailed = false;
let zaiIconPromise: Promise<LobeCompoundIcon | null> | null = null;
let cachedZaiIcon: LobeCompoundIcon | null = null;
let zaiIconLoadFailed = false;

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

const loadQwenIcon = () => {
  if (cachedQwenIcon || qwenIconLoadFailed) {
    return Promise.resolve(cachedQwenIcon);
  }

  qwenIconPromise ??= import("@lobehub/icons")
    .then((module) => {
      cachedQwenIcon = module.Qwen as LobeCompoundIcon;
      return cachedQwenIcon;
    })
    .catch(() => {
      qwenIconLoadFailed = true;
      return null;
    });

  return qwenIconPromise;
};

const loadZaiIcon = () => {
  if (cachedZaiIcon || zaiIconLoadFailed) {
    return Promise.resolve(cachedZaiIcon);
  }

  zaiIconPromise ??= import("@lobehub/icons")
    .then((module) => {
      cachedZaiIcon = module.ZAI as LobeCompoundIcon;
      return cachedZaiIcon;
    })
    .catch(() => {
      zaiIconLoadFailed = true;
      return null;
    });

  return zaiIconPromise;
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
  const [LoadedQwenIcon, setLoadedQwenIcon] =
    useState<LobeCompoundIcon | null>(null);
  const [LoadedZaiIcon, setLoadedZaiIcon] =
    useState<LobeCompoundIcon | null>(null);

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

  useEffect(() => {
    if (provider !== "qwen") {
      return;
    }

    let mounted = true;

    loadQwenIcon().then((component) => {
      if (mounted && component) {
        setLoadedQwenIcon(() => component);
      }
    });

    return () => {
      mounted = false;
    };
  }, [provider]);

  useEffect(() => {
    if (!ZAI_PROVIDER_IDS.has(provider)) {
      return;
    }

    let mounted = true;

    loadZaiIcon().then((component) => {
      if (mounted && component) {
        setLoadedZaiIcon(() => component);
      }
    });

    return () => {
      mounted = false;
    };
  }, [provider]);

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

  if (provider === "qwen") {
    const QwenIcon =
      type === "avatar" ? LoadedQwenIcon?.Avatar : LoadedQwenIcon?.Color;

    if (!QwenIcon) {
      return (
        <span
          aria-hidden="true"
          className={cn("inline-block shrink-0", className)}
          style={{ height: size, width: size }}
        />
      );
    }

    return (
      <QwenIcon
        className={cn("shrink-0 text-foreground", className)}
        size={size}
        type={type}
      />
    );
  }

  if (ZAI_PROVIDER_IDS.has(provider)) {
    const ZaiIcon = type === "avatar" ? LoadedZaiIcon?.Avatar : LoadedZaiIcon;

    if (!ZaiIcon) {
      return (
        <span
          aria-hidden="true"
          className={cn("inline-block shrink-0", className)}
          style={{ height: size, width: size }}
        />
      );
    }

    return (
      <ZaiIcon
        className={cn("shrink-0 text-foreground", className)}
        size={size}
        type={type}
      />
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
