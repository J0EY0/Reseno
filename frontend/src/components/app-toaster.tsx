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
          toast: cn("pr-12!", toastOptions?.classNames?.toast),
          icon: cn("hidden!", toastOptions?.classNames?.icon),
          closeButton: cn(
            "left-auto! right-3! top-1/2! size-8! translate-x-0! -translate-y-1/2! transform-none! rounded-md! border-0! bg-transparent! text-current! opacity-60! shadow-none! transition-[opacity,box-shadow]! hover:bg-transparent! hover:opacity-100! hover:shadow-sm! focus-visible:ring-2! focus-visible:ring-current! focus-visible:ring-offset-1! [&_svg]:size-5!",
            toastOptions?.classNames?.closeButton,
          ),
        },
      }}
      {...props}
    />
  );
}
