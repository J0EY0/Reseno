import type { ComponentProps, CSSProperties } from "react";

import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";

type AppToasterProps = ComponentProps<typeof Toaster>;

export function AppToaster({ toastOptions, ...props }: AppToasterProps) {
  return (
    <Toaster
      richColors
      closeButton
      expand
      visibleToasts={4}
      toastOptions={{
        ...toastOptions,
        style: {
          "--success-bg":
            "color-mix(in oklab, var(--success) 5%, var(--popover))",
          "--success-border":
            "color-mix(in oklab, var(--success) 30%, var(--border))",
          "--success-text": "var(--success)",
          "--warning-bg":
            "color-mix(in oklab, var(--warning) 5%, var(--popover))",
          "--warning-border":
            "color-mix(in oklab, var(--warning) 30%, var(--border))",
          "--warning-text": "var(--warning)",
          "--info-bg":
            "color-mix(in oklab, var(--info) 5%, var(--popover))",
          "--info-border":
            "color-mix(in oklab, var(--info) 30%, var(--border))",
          "--info-text": "var(--info)",
          "--error-bg":
            "color-mix(in oklab, var(--destructive) 5%, var(--popover))",
          "--error-border":
            "color-mix(in oklab, var(--destructive) 30%, var(--border))",
          "--error-text": "var(--destructive)",
          ...toastOptions?.style,
        } as CSSProperties,
        classNames: {
          ...toastOptions?.classNames,
          toast: cn("pr-12!", toastOptions?.classNames?.toast),
          icon: cn("hidden!", toastOptions?.classNames?.icon),
          actionButton: cn(
            "h-8! rounded-md! border! border-current/20! bg-transparent! px-2.5! text-current! shadow-none! transition-colors! duration-200! hover:border-current/35! hover:bg-current/10! focus-visible:ring-2! focus-visible:ring-current! focus-visible:ring-offset-1!",
            toastOptions?.classNames?.actionButton,
          ),
          closeButton: cn(
            "left-auto! right-3! top-1/2! size-8! translate-x-0! -translate-y-1/2! transform-none! rounded-md! border-0! bg-transparent! text-current! opacity-60! shadow-none! transition-opacity! hover:bg-transparent! hover:opacity-100! hover:shadow-none! focus-visible:ring-2! focus-visible:ring-current! focus-visible:ring-offset-1! [&_svg]:size-5!",
            toastOptions?.classNames?.closeButton,
          ),
        },
      }}
      {...props}
    />
  );
}
