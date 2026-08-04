import {
  Award,
  BriefcaseBusiness,
  FolderKanban,
  GraduationCap,
  ListPlus,
  Plus,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'

import type { AppMessages } from '@/i18n'
import { SECTION_KINDS, type SectionKind } from '@/types/resume'

import { Button } from '@/components/ui/button'
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'

const sectionIcons: Record<SectionKind, LucideIcon> = {
  education: GraduationCap,
  experience: BriefcaseBusiness,
  project: FolderKanban,
  achievement: Award,
  simple_list: ListPlus,
}

export function AddSectionPopover({
  t,
  onSelect,
}: {
  t: AppMessages
  onSelect: (kind: SectionKind) => void
}) {
  const [open, setOpen] = useState(false)

  function selectKind(kind: SectionKind) {
    setOpen(false)
    onSelect(kind)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className="h-10 rounded-xl border-dashed bg-background/95"
        >
          <Plus aria-hidden="true" data-icon="inline-start" />
          {t.addSection}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        aria-label={t.addSectionPickerTitle}
        align="center"
        className="w-[360px] max-w-[calc(100vw-2rem)] p-0"
      >
        <Command aria-label={t.addSectionPickerTitle} tabIndex={0}>
          <CommandList
            label={t.addSectionPickerTitle}
            className="max-h-[min(300px,var(--radix-popover-content-available-height))]"
          >
            <CommandGroup>
              {SECTION_KINDS.map((kind) => {
                const Icon = sectionIcons[kind]

                return (
                  <CommandItem
                    key={kind}
                    value={`${t.sectionTitles[kind]} ${t.sectionDescriptions[kind]}`}
                    className="items-start py-2.5"
                    onSelect={() => selectKind(kind)}
                  >
                    <Icon aria-hidden="true" className="mt-0.5" />
                    <span className="grid min-w-0 gap-0.5">
                      <span className="font-medium">{t.sectionTitles[kind]}</span>
                      <span className="text-xs text-muted-foreground">
                        {t.sectionDescriptions[kind]}
                      </span>
                    </span>
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
