import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function GalleryCardSkeleton({ isCreate = false }: { isCreate?: boolean }) {
  return (
    <Card className="h-full gap-0 rounded-(--radius-card) border-border/80 bg-card py-0 text-card-foreground shadow-card">
      <CardContent className="flex h-full flex-col p-2.5">
        <div className="rounded-xl bg-muted/55 p-2">
          {isCreate ? (
            <div className="flex h-[258px] items-center justify-center rounded-lg border border-dashed border-border bg-background">
              <Skeleton className="size-12 rounded-xl bg-primary/90" />
            </div>
          ) : (
            <div className="relative mx-auto h-[258px] w-[182px] overflow-hidden rounded-lg border border-zinc-200 bg-white p-5">
              <div className="grid gap-3">
                <Skeleton className="mx-auto h-4 w-12 bg-zinc-200" />
                <div className="space-y-1.5">
                  <Skeleton className="mx-auto h-2 w-24 bg-zinc-200" />
                  <Skeleton className="mx-auto h-2 w-28 bg-zinc-200" />
                </div>
                <div className="pt-2">
                  <div className="mb-2 flex items-center gap-2">
                    <Skeleton className="h-3 w-8 bg-zinc-200" />
                    <Skeleton className="h-px flex-1 bg-zinc-200" />
                  </div>
                  <div className="space-y-1.5">
                    <Skeleton className="h-2 w-16 bg-zinc-200" />
                    <Skeleton className="h-2 w-full bg-zinc-200" />
                    <Skeleton className="h-2 w-4/5 bg-zinc-200" />
                  </div>
                </div>
                <div className="pt-1">
                  <div className="mb-2 flex items-center gap-2">
                    <Skeleton className="h-3 w-10 bg-zinc-200" />
                    <Skeleton className="h-px flex-1 bg-zinc-200" />
                  </div>
                  <div className="space-y-1.5">
                    <Skeleton className="h-2 w-20 bg-zinc-200" />
                    <Skeleton className="h-2 w-full bg-zinc-200" />
                    <Skeleton className="h-2 w-3/4 bg-zinc-200" />
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="flex min-h-[92px] flex-1 flex-col justify-between px-1 pt-3">
          <div className="grid gap-2">
            <Skeleton className="h-[18px] w-28" />
            <Skeleton className="h-3 w-40" />
            {isCreate ? <Skeleton className="h-3 w-32" /> : null}
          </div>

          {isCreate ? (
            <div className="grid grid-cols-2 gap-2 pt-2.5">
              <Skeleton className="h-8.5 rounded-md bg-primary/90" />
              <Skeleton className="h-8.5 rounded-md bg-background" />
            </div>
          ) : (
            <div className="mt-2 flex items-center gap-1.5">
              <Skeleton className="size-3 rounded-full" />
              <Skeleton className="h-3 w-20" />
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function GalleryWorkspaceSkeleton({
  itemCount,
  includeCreateCard = false,
}: {
  itemCount: number;
  includeCreateCard?: boolean;
}) {
  const visibleItemCount = Math.max(1, itemCount);

  return (
    <section className="rounded-(--radius-workspace) border border-border bg-muted/35 p-3.5 text-foreground sm:p-4">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Skeleton className="h-9 w-full rounded-md bg-card sm:w-80 lg:w-96" />
        <div className="flex items-center gap-2">
          <Skeleton className="h-9 w-24 rounded-md bg-background" />
          <Skeleton className="h-9 w-20 rounded-md bg-primary/90" />
        </div>
        <div className="ml-auto flex w-full justify-end sm:w-auto">
          <Skeleton className="h-9 w-16 rounded-md bg-background" />
        </div>
      </div>

      <div className="grid auto-rows-fr grid-cols-[repeat(auto-fill,minmax(208px,228px))] justify-center gap-4">
        {includeCreateCard ? <GalleryCardSkeleton isCreate /> : null}
        {Array.from({ length: visibleItemCount }).map((_, index) => (
          <GalleryCardSkeleton key={index} />
        ))}
      </div>

      {visibleItemCount > 1 ? (
        <div className="mt-4 flex items-center justify-center gap-2">
          <Skeleton className="size-8 rounded-lg bg-background" />
          <Skeleton className="h-8 w-16 rounded-lg bg-background" />
          <Skeleton className="size-8 rounded-lg bg-background" />
        </div>
      ) : null}
    </section>
  );
}

export function GalleryRouteSkeleton({
  itemCount,
  includeCreateCard = false,
}: {
  itemCount: number;
  includeCreateCard?: boolean;
}) {
  return (
    <div data-slot="gallery-route-skeleton" className="flex-1 p-4">
      <GalleryWorkspaceSkeleton
        itemCount={itemCount}
        includeCreateCard={includeCreateCard}
      />
    </div>
  );
}
