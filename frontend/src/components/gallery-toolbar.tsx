import { Search, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function GalleryToolbar({
  searchPlaceholder,
  searchValue,
  onSearchChange,
  isSelecting,
  onToggleSelecting,
  selectedCount,
  selectLabel,
  cancelLabel,
  bulkDeleteLabel,
  onBulkDelete,
}: {
  searchPlaceholder: string;
  searchValue: string;
  onSearchChange: (value: string) => void;
  isSelecting: boolean;
  onToggleSelecting: () => void;
  selectedCount: number;
  selectLabel: string;
  cancelLabel: string;
  bulkDeleteLabel: string;
  onBulkDelete: () => void;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <div className="relative w-full max-w-[250px] sm:max-w-[280px]">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={searchValue}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={searchPlaceholder}
          className="h-9 rounded-full border-border bg-card pl-9 shadow-sm"
        />
      </div>

      <div className="ml-auto flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
        <Button
          type="button"
          variant={isSelecting ? "secondary" : "outline"}
          size="sm"
          className="h-9 rounded-full"
          onClick={onToggleSelecting}
        >
          {isSelecting ? cancelLabel : selectLabel}
        </Button>

        {isSelecting && selectedCount > 0 ? (
          <Badge variant="outline" className="h-9 rounded-full px-3 text-sm">
            {selectedCount}
          </Badge>
        ) : null}

        {isSelecting && selectedCount >= 2 ? (
          <Button
            type="button"
            size="sm"
            className="h-9 rounded-full border border-red-600 bg-red-600 text-white hover:bg-red-600/90"
            onClick={onBulkDelete}
          >
            <Trash2 className="size-4" />
            {bulkDeleteLabel}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
