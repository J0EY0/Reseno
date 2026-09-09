import type { ComponentProps } from "react";
import type { OAuthLoginControls } from "@/hooks/use-oauth-login";
import { AuthPageShell } from "@/components/auth/auth-page-shell";
import { LoginForm } from "@/components/auth/login-form";

export function LoginPage(
  props: ComponentProps<typeof LoginForm> & { oauth: OAuthLoginControls },
) {
  return (
    <AuthPageShell
      brandTitle={props.t.brandTitle}
      formTitle={props.t.loginFormTitle}
      description={props.t.loginFormSubtitle}
    >
      <LoginForm {...props} />
    </AuthPageShell>
  );
}
