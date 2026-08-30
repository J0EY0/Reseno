import { Search, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group";

export function GalleryToolbar({
  searchLabel,
  searchName,
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
  searchLabel: string;
  searchName: string;
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
  const canBulkDelete = isSelecting && selectedCount >= 2;
  const [isComposing, setIsComposing] = useState(false);
  const [searchDraft, setSearchDraft] = useState(() => ({
    committedValue: searchValue,
    value: searchValue,
  }));

  if (!isComposing && searchDraft.committedValue !== searchValue) {
    setSearchDraft({ committedValue: searchValue, value: searchValue });
  }

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <InputGroup className="w-full sm:w-80 lg:w-96">
        <InputGroupAddon>
          <Search aria-hidden="true" />
        </InputGroupAddon>
        <InputGroupInput
          aria-label={searchLabel}
          name={searchName}
          autoComplete="off"
          spellCheck={false}
          value={searchDraft.value}
          onCompositionStart={() => {
            setIsComposing(true);
          }}
          onCompositionEnd={(event) => {
            const value = event.currentTarget.value;
            setIsComposing(false);
            setSearchDraft((current) => ({
              ...current,
              value,
            }));
            onSearchChange(value);
          }}
          onChange={(event) => {
            const value = event.currentTarget.value;
            const nativeEvent = event.nativeEvent as InputEvent;
            setSearchDraft((current) => ({ ...current, value }));

            if (
              isComposing ||
              nativeEvent.isComposing ||
              nativeEvent.inputType === "insertCompositionText"
            ) {
              return;
            }

            onSearchChange(value);
          }}
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
          size="default"
          onClick={onToggleSelecting}
        >
          {isSelecting ? cancelLabel : selectLabel}
        </Button>

        {isSelecting && selectedCount > 0 ? (
          <Badge variant="outline" aria-live="polite">
            <span
              key={selectedCount}
              className="inline-block animate-in fade-in-0 zoom-in-95 duration-150"
            >
              {selectedCount}
            </span>
          </Badge>
        ) : null}

        <div
          data-gallery-bulk-action=""
          data-state={canBulkDelete ? "open" : "closed"}
          aria-hidden={!canBulkDelete}
          inert={!canBulkDelete}
          className={`grid min-w-0 transition-all duration-150 ease-out ${
            canBulkDelete ? "" : "pointer-events-none"
          }`}
          style={{
            gridTemplateColumns: canBulkDelete ? "1fr" : "0fr",
            marginLeft: canBulkDelete ? 0 : "-0.5rem",
            opacity: canBulkDelete ? 1 : 0,
            transform: canBulkDelete
              ? "translateX(0) scale(1)"
              : "translateX(0.25rem) scale(0.98)",
            transformOrigin: "right center",
          }}
        >
          <div className="min-w-0 overflow-hidden">
            <Button
              type="button"
              variant="destructive"
              size="default"
              tabIndex={canBulkDelete ? undefined : -1}
              onClick={onBulkDelete}
            >
              <Trash2 data-icon="inline-start" />
              {bulkDeleteLabel}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
