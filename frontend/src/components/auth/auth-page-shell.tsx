import type { ReactNode } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AppToaster } from "@/components/app-toaster";

export function AuthPageShell({
  children,
  description,
  formTitle,
  title,
}: {
  children: ReactNode;
  description?: string;
  formTitle: string;
  title: ReactNode;
}) {
  return (
    <main className="relative min-h-svh overflow-hidden bg-background text-foreground">
      <AppToaster position="bottom-right" />
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(24,24,27,0.08),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(24,24,27,0.06),transparent_24%)]" />
      <div className="relative flex min-h-svh items-center justify-center p-5 sm:p-8">
        <Card className="w-full max-w-5xl overflow-hidden rounded-(--radius-workspace) border-border/80 shadow-none">
          <div className="grid lg:grid-cols-[1.08fr_0.92fr]">
            <div className="flex items-center border-b border-border bg-muted/25 p-8 lg:border-b-0 lg:border-r lg:p-10">
              <div>
                <h1 className="max-w-[10ch] text-5xl font-black tracking-[-0.07em] text-foreground sm:text-6xl">
                  {title}
                </h1>
              </div>
            </div>

            <div className="flex p-8 lg:p-10">
              <div className="w-full self-center">
                <CardHeader className="p-0">
                  <CardTitle className="text-3xl font-bold tracking-tight">
                    {formTitle}
                  </CardTitle>
                  {description ? (
                    <CardDescription>{description}</CardDescription>
                  ) : null}
                </CardHeader>

                <CardContent className="p-0 pt-8">{children}</CardContent>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </main>
  );
}
