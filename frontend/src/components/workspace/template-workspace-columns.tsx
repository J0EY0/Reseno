import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { ResourceErrorBoundary } from "@/components/resource-error-boundary";
import {
  readTemplateEditorWidth,
  resolveTemplateWorkspaceWidth,
  writeTemplateEditorWidth,
} from "@/components/workspace/template-workspace-layout";
import type { Locale } from "@/i18n";

import "./template-workspace-columns.css";

const WorkspaceResizer = lazy(() => import("./template-workspace-resizer"));

export function TemplateWorkspaceColumns({
  editor,
  children,
  locale,
}: {
  editor: ReactNode;
  children: ReactNode;
  locale: Locale;
}) {
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(() => window.innerWidth);
  const [desktop, setDesktop] = useState(
    () => window.matchMedia("(min-width: 1280px)").matches,
  );
  const [preference, setPreference] = useState(readTemplateEditorWidth);
  const { width, minimum, maximum } = resolveTemplateWorkspaceWidth(
    containerWidth,
    preference,
    locale,
  );

  useEffect(() => {
    const element = workspaceRef.current;
    if (!element) return;
    const media = window.matchMedia("(min-width: 1280px)");
    const syncDesktop = () => setDesktop(media.matches);
    const observer = new ResizeObserver(([entry]) =>
      setContainerWidth(Math.round(entry.contentRect.width)),
    );
    observer.observe(element);
    media.addEventListener("change", syncDesktop);
    return () => {
      observer.disconnect();
      media.removeEventListener("change", syncDesktop);
    };
  }, []);

  const commit = (templateEditorWidth: number) => {
    workspaceRef.current?.removeAttribute("data-resizing");
    setPreference(templateEditorWidth);
    writeTemplateEditorWidth(templateEditorWidth);
  };

  return (
    <div
      ref={workspaceRef}
      lang={locale}
      className="workspace-document-enter template-workspace"
      style={{ "--template-editor-width": `${width}px` } as CSSProperties}
    >
      <div className="template-editor-column relative min-w-0 print:hidden">
        {editor}
        {desktop ? (
          <ResourceErrorBoundary>
            <Suspense fallback={null}>
              <WorkspaceResizer
                locale={locale}
                width={width}
                min={minimum}
                max={maximum}
                onResizeStart={() =>
                  workspaceRef.current?.setAttribute("data-resizing", "true")
                }
                onResize={(nextWidth) =>
                  workspaceRef.current?.style.setProperty(
                    "--template-editor-width",
                    `${nextWidth}px`,
                  )
                }
                onCommit={commit}
                onReset={() => commit(minimum)}
              />
            </Suspense>
          </ResourceErrorBoundary>
        ) : null}
      </div>
      {children}
    </div>
  );
}
