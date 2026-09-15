import { UserRound } from "lucide-react";
import { lazy, startTransition, Suspense } from "react";

import type { BasicInfoFieldsProps } from "./basic-info-fields";
import { EditorCardShell } from "./editor-card-shell";

const BasicInfoFields = lazy(() =>
  import("./basic-info-fields").then((module) => ({
    default: module.BasicInfoFields,
  })),
);

export function BasicInfoCard({
  collapsed,
  onToggle,
  ...props
}: BasicInfoFieldsProps & {
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <Suspense fallback={null}>
      <EditorCardShell
        icon={UserRound}
        title={props.t.basicInfo}
        toggleLabel={`${props.t.basicInfo}: ${props.t.toggleSection}`}
        collapsed={collapsed}
        onToggle={() => startTransition(onToggle)}
      >
        <BasicInfoFields {...props} />
      </EditorCardShell>
    </Suspense>
  );
}
