import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export function WorkspacePanelSkeleton() {
  return (
    <div data-slot="workspace-panel-skeleton" className="grid gap-2.5">
      {Array.from({ length: 4 }).map((_, index) => (
        <Card
          key={index}
          className="gap-0 border-border/75 bg-card py-0"
        >
          <CardContent className="p-0">
            <div className="flex min-h-[60px] items-center gap-2.5 px-4 py-3">
              <Skeleton className="size-9 rounded-xl" />
              <div className="grid flex-1 gap-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-3 w-40" />
              </div>
              <Skeleton className="size-9 rounded-xl" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function WorkspacePreviewSkeleton() {
  return (
    <section
      data-slot="workspace-preview-skeleton"
      className="resume-preview-card relative flex min-w-0 flex-col overflow-hidden rounded-(--radius-preview) border border-border bg-card p-4 xl:self-start"
    >
      <div className="flex justify-center">
        <div className="w-[min(100%,640px)] rounded-md border border-border bg-background p-10 shadow-card">
          <div className="mx-auto grid max-w-[520px] gap-5">
            <Skeleton className="mx-auto h-8 w-32" />
            <Skeleton className="mx-auto h-4 w-72" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="mt-2 grid gap-3">
                <div className="flex items-center gap-3">
                  <Skeleton className="h-6 w-24" />
                  <Skeleton className="h-px flex-1" />
                </div>
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function WorkspaceContentSkeleton() {
  return (
    <Card className="min-h-[520px] rounded-(--radius-workspace) border-border/80 shadow-none">
      <CardContent className="space-y-6 p-6">
        <div className="flex items-center justify-between gap-4">
          <div className="grid gap-2">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-3 w-64" />
          </div>
          <Skeleton className="h-10 w-28 rounded-md" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton
              key={index}
              className="h-56 rounded-(--radius-card)"
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function ModelConfigPanelSkeleton() {
  const columns = [null, "w-24", "w-20", "w-32", "w-20", "w-16"];

  return (
    <div
      data-slot="model-config-panel-skeleton"
      aria-busy="true"
      className="grid gap-4"
    >
      <Card className="min-w-0 rounded-(--radius-workspace) border-border/80 bg-muted/35 shadow-none py-0">
        <CardContent className="grid min-w-0 gap-4 p-4">
          <div className="flex items-center justify-between gap-3">
            <Skeleton className="h-6 w-28 rounded-full" />
            <Skeleton className="h-9 w-28 rounded-md" />
          </div>
          <div
            data-slot="model-config-content-skeleton"
            className="flex min-h-[390px] min-w-0 flex-col gap-4"
          >
            <div
              data-slot="data-table-skeleton"
              className="w-full min-w-0 max-w-full overflow-hidden rounded-lg border bg-card"
            >
              <Table className="min-w-[760px]">
                <TableHeader className="bg-muted">
                  <TableRow>
                    {columns.map((width, index) => (
                      <TableHead key={index}>
                        <Skeleton
                          className={
                            width ? `h-3 ${width}` : "size-4 rounded-[4px]"
                          }
                        />
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Array.from({ length: 4 }).map((_, rowIndex) => (
                    <TableRow key={rowIndex} className="h-12">
                      {columns.map((width, columnIndex) => (
                        <TableCell key={columnIndex}>
                          <Skeleton
                            className={
                              width ? `h-4 ${width}` : "size-4 rounded-[4px]"
                            }
                          />
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

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

export function WorkspaceRouteSkeleton() {
  return (
    <div data-slot="workspace-route-skeleton" className="flex-1 p-4">
      <WorkspaceContentSkeleton />
    </div>
  );
}
