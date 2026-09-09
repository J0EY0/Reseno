import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

export function ModelConfigBulkDeleteAction({
  label,
  selectedCount,
  disabled,
  isPending,
  onDelete,
}: {
  label: string;
  selectedCount: number;
  disabled: boolean;
  isPending: boolean;
  onDelete: () => void;
}) {
  const canBulkDelete = selectedCount > 0;

  return (
    <div
      data-slot="model-config-bulk-actions"
      data-state={canBulkDelete ? "open" : "closed"}
      aria-hidden={!canBulkDelete}
      inert={!canBulkDelete}
      className={cn(
        "transition-[opacity,transform]",
        canBulkDelete
          ? "opacity-100 [transform:translateX(0)] [transition-duration:var(--duration-enter)] [transition-timing-function:var(--ease-move)]"
          : "pointer-events-none opacity-0 [transform:translateX(0.25rem)] [transition-duration:var(--duration-exit)] ease-in",
      )}
    >
      <Button
        type="button"
        variant="destructive"
        size="default"
        tabIndex={canBulkDelete ? undefined : -1}
        disabled={disabled}
        onClick={onDelete}
      >
        {isPending ? (
          <Spinner data-icon="inline-start" aria-label={label} />
        ) : (
          <Trash2 data-icon="inline-start" />
        )}
        {label}
      </Button>
    </div>
  );
}
