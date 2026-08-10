import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { AppMessages } from "@/i18n";

export function WorkspaceRouteError({
  messages,
  onRetry,
}: {
  messages: AppMessages;
  onRetry: () => void;
}) {
  return (
    <div className="flex flex-1 p-4">
      <Card className="flex min-h-80 flex-1 items-center justify-center rounded-3xl border-border/80 shadow-sm">
        <CardContent className="flex flex-col items-center gap-4 p-6 text-center">
          <p className="text-sm text-muted-foreground">
            {messages.contentNotLoaded}
          </p>
          <Button type="button" variant="outline" onClick={onRetry}>
            {messages.retry}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
