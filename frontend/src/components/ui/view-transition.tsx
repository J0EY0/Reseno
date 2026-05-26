import * as React from "react";

type ViewTransitionClass = string | Record<string, string>;

interface ViewTransitionBoundaryProps {
  children: React.ReactNode;
  name?: string;
  default?: ViewTransitionClass;
  enter?: ViewTransitionClass;
  exit?: ViewTransitionClass;
  update?: ViewTransitionClass;
  share?: ViewTransitionClass;
}

const NativeViewTransition = (
  React as unknown as {
    ViewTransition?: React.ComponentType<ViewTransitionBoundaryProps>;
  }
).ViewTransition;

export function ViewTransitionBoundary({
  children,
  ...props
}: ViewTransitionBoundaryProps) {
  if (!NativeViewTransition) {
    return <>{children}</>;
  }

  return <NativeViewTransition {...props}>{children}</NativeViewTransition>;
}

