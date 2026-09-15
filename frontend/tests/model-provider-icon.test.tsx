import { Bot } from "lucide-react";
import type { ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ModelProviderIcon } from "@/components/model-provider-icon";

const providers = [
  ["anthropic", () => import("@lobehub/icons/es/Anthropic")],
  ["deepseek", () => import("@lobehub/icons/es/DeepSeek")],
  ["google", () => import("@lobehub/icons/es/Google")],
  ["minimax", () => import("@lobehub/icons/es/Minimax")],
  ["moonshot", () => import("@lobehub/icons/es/Moonshot")],
  ["ollama", () => import("@lobehub/icons/es/Ollama")],
  ["openai", () => import("@lobehub/icons/es/OpenAI")],
  ["qwen", () => import("@lobehub/icons/es/Qwen")],
  ["vllm", () => import("@lobehub/icons/es/Vllm")],
  ["xai", () => import("@lobehub/icons/es/XAI")],
  ["zai", () => import("@lobehub/icons/es/ZAI")],
] as const;

const referenceProviders = await Promise.all(
  providers.map(
    async ([provider, loadReference]) =>
      [provider, (await loadReference()).default] as const,
  ),
);

const renderIcon = (props: ComponentProps<typeof ModelProviderIcon>) =>
  renderToStaticMarkup(<ModelProviderIcon {...props} />);

describe("Model provider icons", () => {
  it.each(referenceProviders)(
    "preserves %s artwork, styling, and default or explicit size",
    (provider, icon) => {
      const ExpectedIcon = "Color" in icon ? icon.Color : icon;
      for (const props of [
        { provider },
        { provider, size: 16, className: "provider-test" },
        { provider, size: 28, className: "provider-test" },
      ]) {
        expect(renderIcon(props)).toBe(
          renderToStaticMarkup(
            <ExpectedIcon
              className={`shrink-0${ExpectedIcon === icon ? " text-foreground" : ""}${props.className ? ` ${props.className}` : ""}`}
              size={props.size ?? 20}
            />,
          ),
        );
      }
    },
  );

  it.each([
    ["custom-cloud", "openai"],
    ["glm", "zai"],
    ["google-vertex", "google"],
    ["google-vertex-anthropic", "anthropic"],
    ["moonshotai", "moonshot"],
    ["zhipu", "zai"],
    ["zhipuai", "zai"],
  ])("renders %s as %s", (alias, provider) => {
    expect(renderIcon({ provider: alias })).toBe(renderIcon({ provider }));
  });

  it.each([16, 28])(
    "retains the SGLang text mark and unknown-provider icon at %ipx",
    (size) => {
      expect(renderIcon({ provider: "unknown-provider", size })).toBe(
        renderToStaticMarkup(
          <Bot
            aria-hidden="true"
            className="shrink-0 text-muted-foreground"
            size={size}
          />,
        ),
      );
      expect(renderIcon({ provider: "sglang", size })).toBe(
        renderToStaticMarkup(
          <span
            aria-label="SGLang"
            className="inline-flex shrink-0 items-center justify-center font-semibold leading-none text-foreground"
            style={{ fontSize: size === 16 ? 10 : 13 }}
          >
            SG
          </span>,
        ),
      );
    },
  );
});
