import type { ComponentProps } from "react";

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
        classNames: {
          ...toastOptions?.classNames,
          toast: cn("pr-10!", toastOptions?.classNames?.toast),
          closeButton: cn(
            "left-auto! right-2! top-1/2! translate-x-0! -translate-y-1/2!",
            toastOptions?.classNames?.closeButton,
          ),
        },
      }}
      {...props}
    />
  );
}
