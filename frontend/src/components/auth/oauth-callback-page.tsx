import GithubIcon from "@lobehub/icons/es/Github/components/Mono";
import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AppMessages } from "@/i18n";

export function OAuthCallbackPage({ t }: { t: AppMessages }) {
  useEffect(() => {
    window.history.replaceState(
      window.history.state,
      "",
      window.location.pathname,
    );
  }, []);

  return (
    <main className="flex min-h-svh items-center justify-center bg-muted p-6 text-foreground">
      <Card className="w-full max-w-sm text-center shadow-none">
        <CardHeader className="items-center gap-3">
          <GithubIcon className="size-8" aria-hidden="true" />
          <CardTitle>{t.oauthCallbackErrorTitle}</CardTitle>
          <CardDescription role="alert">
            {t.oauthTabUnavailable}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => window.close()}>
            {t.oauthTabClose}
          </Button>
        </CardContent>
      </Card>
    </main>
  );
}
