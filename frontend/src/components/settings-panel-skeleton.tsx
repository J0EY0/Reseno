import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function SettingsSectionSkeleton({ rowCount }: { rowCount: number }) {
  return (
    <section className="grid gap-3">
      <Skeleton className="mx-1 h-5 w-32" />
      <Card className="gap-0 overflow-hidden py-0">
        {Array.from({ length: rowCount }).map((_, index) => (
          <div
            key={index}
            className="grid min-h-20 gap-4 border-b border-border px-5 py-4 last:border-b-0 sm:min-h-16 sm:grid-cols-[minmax(0,1fr)_minmax(16rem,22rem)] sm:items-center sm:gap-6 sm:px-6 sm:py-3"
          >
            <div className="flex items-center gap-3">
              <Skeleton className="size-7 rounded-md" />
              <div className="grid gap-2">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-3 w-44" />
              </div>
            </div>
            <Skeleton className="h-9 w-full rounded-md" />
          </div>
        ))}
      </Card>
    </section>
  );
}

export function SettingsPanelSkeleton() {
  return (
    <div
      data-slot="settings-panel-skeleton"
      className="flex flex-1 items-start p-4 sm:p-6 lg:p-8"
    >
      <div className="mx-auto w-full max-w-6xl">
        <Skeleton className="h-9 w-full rounded-md" />
        <div className="mt-5 flex flex-col gap-6">
          <SettingsSectionSkeleton rowCount={2} />
          <SettingsSectionSkeleton rowCount={1} />
        </div>
      </div>
    </div>
  );
}
