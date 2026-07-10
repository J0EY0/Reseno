import { Search, Trash2 } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group";

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
  leadingActions,
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
  leadingActions?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <InputGroup className="w-full sm:w-80 lg:w-96">
        <InputGroupAddon>
          <Search aria-hidden="true" />
        </InputGroupAddon>
        <InputGroupInput
          value={searchValue}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder={searchPlaceholder}
        />
      </InputGroup>

      {leadingActions ? (
        <div className="flex flex-wrap items-center gap-2">{leadingActions}</div>
      ) : null}

      <div className="ml-auto flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto">
        <Button
          type="button"
          variant={isSelecting ? "secondary" : "outline"}
          size="sm"
          onClick={onToggleSelecting}
        >
          {isSelecting ? cancelLabel : selectLabel}
        </Button>

        {isSelecting && selectedCount > 0 ? (
          <Badge variant="outline">
            {selectedCount}
          </Badge>
        ) : null}

        {isSelecting && selectedCount >= 2 ? (
          <Button
            type="button"
            variant="destructive"
            size="sm"
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
