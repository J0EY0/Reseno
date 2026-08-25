import { cn } from "@/lib/utils";
import type { Components } from "streamdown";

export function createAgentMarkdownComponents(
  fieldLabels: ReadonlyMap<string, string>,
): Components {
  return {
    inlineCode: ({ children, className }) => {
      const token = typeof children === "string" ? children.trim() : "";
      const displayLabel = fieldLabels.get(token);

      if (displayLabel) {
        return <span className="font-medium text-foreground">{displayLabel}</span>;
      }

      return (
        <code
          className={cn(
            "rounded bg-muted px-1.5 py-0.5 font-mono text-sm",
            className,
          )}
          data-streamdown="inline-code"
        >
          {children}
        </code>
      );
    },
  };
}

export function getAgentMarkdownFallbackText(
  text: string,
  fieldLabels: ReadonlyMap<string, string>,
) {
  let projectedText = text;

  for (const [token, displayLabel] of fieldLabels) {
    projectedText = projectedText.replaceAll(`\`${token}\``, () => displayLabel);
  }

  return projectedText;
}
