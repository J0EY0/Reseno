import type { ReactNode } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AppToaster } from "@/components/app-toaster";
import { AuthParticleBackground } from "@/components/auth/auth-particle-background";

export function AuthPageShell({
  brandTitle,
  children,
  description,
  formTitle,
}: {
  brandTitle: string;
  children: ReactNode;
  description?: string;
  formTitle: string;
}) {
  return (
    <main className="flex min-h-svh items-center justify-center bg-muted p-6 text-foreground md:p-10">
      <AppToaster position="bottom-right" />
      <Card className="w-full max-w-sm gap-0 overflow-hidden rounded-(--radius-workspace) p-0 shadow-none md:max-w-4xl">
        <div className="grid md:min-h-120 md:grid-cols-2">
          <div className="flex min-w-0 items-center p-6 md:p-8">
            <div className="w-full">
              <CardHeader className="gap-2 p-0 text-center">
                <CardTitle>
                  <h1 className="text-2xl font-bold tracking-tight">
                    {formTitle}
                  </h1>
                </CardTitle>
                {description ? (
                  <CardDescription className="text-balance">
                    {description}
                  </CardDescription>
                ) : null}
              </CardHeader>

              <CardContent className="p-0 pt-8">{children}</CardContent>
            </div>
          </div>
          <div
            aria-hidden="true"
            className="relative hidden overflow-hidden md:block"
          >
            <AuthParticleBackground />
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center bg-linear-to-t from-(--auth-particle-edge)/85 via-(--auth-particle-edge)/30 to-transparent px-8 pt-20 pb-8 lg:pb-10">
              <p className="text-4xl leading-none font-semibold tracking-tight text-(--auth-particle-foreground)">
                {brandTitle}
              </p>
            </div>
          </div>
        </div>
      </Card>
    </main>
  );
}
