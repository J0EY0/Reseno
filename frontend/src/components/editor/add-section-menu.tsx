import {
  Award,
  BriefcaseBusiness,
  FolderKanban,
  GraduationCap,
  LibraryBig,
  ListPlus,
  type LucideIcon,
} from "lucide-react";

import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import type { AppMessages } from "@/i18n";
import { SECTION_KINDS, type SectionKind } from "@/types/resume";

const sectionIcons: Record<SectionKind, LucideIcon> = {
  education: GraduationCap,
  experience: BriefcaseBusiness,
  project: FolderKanban,
  publication: LibraryBig,
  achievement: Award,
  simple_list: ListPlus,
};

function focusMenu(element: HTMLDivElement | null) {
  element?.focus();
}

export default function AddSectionMenu({
  t,
  onSelect,
}: {
  t: AppMessages;
  onSelect: (kind: SectionKind) => void;
}) {
  return (
    <Command ref={focusMenu} aria-label={t.addSectionPickerTitle} tabIndex={0}>
      <CommandList
        label={t.addSectionPickerTitle}
        className="max-h-[min(300px,var(--radix-popover-content-available-height))]"
      >
        <CommandGroup>
          {SECTION_KINDS.map((kind) => {
            const Icon = sectionIcons[kind];

            return (
              <CommandItem
                key={kind}
                value={`${t.sectionTitles[kind]} ${t.sectionDescriptions[kind]}`}
                className="items-start py-2.5"
                onSelect={() => onSelect(kind)}
              >
                <Icon aria-hidden="true" className="mt-0.5" />
                <span className="grid min-w-0 gap-0.5">
                  <span className="font-medium">{t.sectionTitles[kind]}</span>
                  <span className="text-xs text-muted-foreground">
                    {t.sectionDescriptions[kind]}
                  </span>
                </span>
              </CommandItem>
            );
          })}
        </CommandGroup>
      </CommandList>
    </Command>
  );
}
