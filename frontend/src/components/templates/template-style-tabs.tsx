import { Tabs as TabsPrimitive } from "@base-ui/react/tabs";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

import "./template-style-tabs.css";

type StyledProps<T> = Omit<T, "className"> & { className?: string };

export function TemplateStyleTabs(
  props: ComponentProps<typeof TabsPrimitive.Root>,
) {
  return <TabsPrimitive.Root data-slot="tabs" {...props} />;
}

export function TemplateStyleTabsList({
  className,
  children,
  size = "default",
  ...props
}: StyledProps<ComponentProps<typeof TabsPrimitive.List>> & {
  size?: "default" | "sm";
}) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-size={size}
      activateOnFocus
      className={cn("template-style-tabs-list", className)}
      {...props}
    >
      <TabsPrimitive.Indicator
        data-slot="template-tabs-indicator"
        className="template-style-tabs-indicator"
      />
      {children}
    </TabsPrimitive.List>
  );
}

export function TemplateStyleTabsTrigger({
  className,
  ...props
}: StyledProps<ComponentProps<typeof TabsPrimitive.Tab>>) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn("template-style-tabs-trigger", className)}
      {...props}
    />
  );
}

export function TemplateStyleTabsContent({
  className,
  animate = false,
  ...props
}: StyledProps<ComponentProps<typeof TabsPrimitive.Panel>> & {
  animate?: boolean;
}) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      data-animate={animate || undefined}
      className={cn("template-style-tabs-content outline-none", className)}
      {...props}
    />
  );
}
