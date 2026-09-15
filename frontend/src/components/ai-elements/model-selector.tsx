import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { ModelProviderIcon } from "@/components/model-provider-icon";
import { cn } from "@/lib/utils";
import type { ComponentProps, ReactNode } from "react";

type ModelSelectorProps = ComponentProps<typeof Dialog>;

export const ModelSelector = (props: ModelSelectorProps) => (
  <Dialog {...props} />
);

type ModelSelectorTriggerProps = ComponentProps<typeof DialogTrigger>;

export const ModelSelectorTrigger = (props: ModelSelectorTriggerProps) => (
  <DialogTrigger {...props} />
);

type ModelSelectorContentProps = ComponentProps<typeof DialogContent> & {
  title?: ReactNode;
};

export const ModelSelectorContent = ({
  className,
  children,
  title = "Model Selector",
  ...props
}: ModelSelectorContentProps) => (
  <DialogContent
    aria-describedby={undefined}
    className={cn(
      "outline! border-none! p-0 outline-border! outline-solid!",
      className,
    )}
    {...props}
  >
    <DialogTitle className="sr-only">{title}</DialogTitle>
    <Command className="**:data-[slot=command-input-wrapper]:h-auto">
      {children}
    </Command>
  </DialogContent>
);

type ModelSelectorInputProps = ComponentProps<typeof CommandInput>;

export const ModelSelectorInput = ({
  className,
  ...props
}: ModelSelectorInputProps) => (
  <CommandInput className={cn("h-auto py-3.5", className)} {...props} />
);

type ModelSelectorListProps = ComponentProps<typeof CommandList>;

export const ModelSelectorList = (props: ModelSelectorListProps) => (
  <CommandList {...props} />
);

type ModelSelectorEmptyProps = ComponentProps<typeof CommandEmpty>;

export const ModelSelectorEmpty = (props: ModelSelectorEmptyProps) => (
  <CommandEmpty {...props} />
);

type ModelSelectorGroupProps = ComponentProps<typeof CommandGroup>;

export const ModelSelectorGroup = (props: ModelSelectorGroupProps) => (
  <CommandGroup {...props} />
);

type ModelSelectorItemProps = ComponentProps<typeof CommandItem>;

export const ModelSelectorItem = (props: ModelSelectorItemProps) => (
  <CommandItem {...props} />
);

type ModelSelectorLogoProps = Omit<
  ComponentProps<typeof ModelProviderIcon>,
  "provider"
> & {
  provider:
    | "moonshotai-cn"
    | "lucidquery"
    | "moonshotai"
    | "zai-coding-plan"
    | "alibaba"
    | "xai"
    | "vultr"
    | "upstage"
    | "github-copilot"
    | "minimax"
    | "mistral"
    | "vercel"
    | "nebius"
    | "deepseek"
    | "alibaba-cn"
    | "google-vertex-anthropic"
    | "venice"
    | "chutes"
    | "cortecs"
    | "github-models"
    | "azure"
    | "baseten"
    | "huggingface"
    | "opencode"
    | "fastrouter"
    | "google"
    | "google-vertex"
    | "cloudflare-workers-ai"
    | "inception"
    | "wandb"
    | "openai"
    | "zhipuai-coding-plan"
    | "perplexity"
    | "openrouter"
    | "zenmux"
    | "v0"
    | "iflowcn"
    | "synthetic"
    | "deepinfra"
    | "zhipuai"
    | "submodel"
    | "zai"
    | "inference"
    | "requesty"
    | "morph"
    | "lmstudio"
    | "anthropic"
    | "aihubmix"
    | "modelscope"
    | "llama"
    | "scaleway"
    | "amazon-bedrock"
    // oxlint-disable-next-line typescript-eslint(ban-types) -- intentional pattern for autocomplete-friendly string union
    | (string & {});
};

export const ModelSelectorLogo = ({
  provider,
  className,
  size = 16,
  ...props
}: ModelSelectorLogoProps) => (
  <ModelProviderIcon
    {...props}
    className={cn(
      "inline-flex size-4 shrink-0 items-center justify-center text-foreground",
      className,
    )}
    provider={provider}
    size={size}
  />
);

type ModelSelectorNameProps = ComponentProps<"span">;

export const ModelSelectorName = ({
  className,
  ...props
}: ModelSelectorNameProps) => (
  <span className={cn("flex-1 truncate text-left", className)} {...props} />
);
