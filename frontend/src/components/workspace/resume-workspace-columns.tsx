import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { ResizableWorkspacePanel } from "@/components/workspace/resizable-workspace-panel";
import {
  AGENT_MIN_WIDTH,
  DEFAULT_AGENT_WIDTH,
  EDITOR_MIN_WIDTH,
  PREVIEW_MIN_WIDTH,
  getDefaultEditorWidth,
  readWorkspaceLayoutPreference,
  resolveWorkspaceWidths,
  writeWorkspaceLayoutPreference,
  type WorkspaceLayoutPreference,
} from "@/components/workspace/resume-workspace-layout";
import type { Locale } from "@/i18n";
import workspaceResizeMessages from "@/i18n/workspace-resize.json";

import "./resume-workspace-columns.css";

export function ResumeWorkspaceColumns({
  editor,
  preview,
  agent,
  agentExpanded,
  locale,
}: {
  editor: ReactNode;
  preview: ReactNode;
  agent: ReactNode;
  agentExpanded: boolean;
  locale: Locale;
}) {
  const messages = workspaceResizeMessages[locale];
  const workspaceRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(() => window.innerWidth);
  const [desktop, setDesktop] = useState(
    () => window.matchMedia("(min-width: 1280px)").matches,
  );
  const [preference, setPreference] = useState(readWorkspaceLayoutPreference);
  const { editorWidth, agentWidth, editorMaxWidth, agentMaxWidth } =
    resolveWorkspaceWidths(containerWidth, preference, agentExpanded);

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

  const startResize = () => {
    workspaceRef.current?.setAttribute("data-resizing", "true");
  };
  const updateLiveWidth = (panel: "editor" | "agent", width: number) => {
    workspaceRef.current?.style.setProperty(
      `--${panel}-panel-width`,
      `${width}px`,
    );
  };
  const commit = (patch: WorkspaceLayoutPreference) => {
    workspaceRef.current?.removeAttribute("data-resizing");
    setPreference((current) => ({ ...current, ...patch }));
    writeWorkspaceLayoutPreference(patch);
  };
  const style = {
    "--editor-panel-width": `${editorWidth}px`,
    "--agent-panel-width": `${agentWidth}px`,
    "--document-sticky-bottom-gap": "0px",
    "--document-workspace-gutter": "0px",
    "--resume-workspace-columns": `var(--editor-panel-width) minmax(${PREVIEW_MIN_WIDTH}px,1fr) ${agentExpanded ? "var(--agent-panel-width)" : "0px"}`,
  } as CSSProperties;

  return (
    <div
      ref={workspaceRef}
      style={style}
      data-agent-expanded={agentExpanded}
      className="workspace-document-enter resume-workspace relative grid min-w-0 flex-1 gap-y-4 gap-x-3 p-4 print:block print:h-auto print:overflow-visible print:p-0"
    >
      <ResizableWorkspacePanel
        className="workspace-editor-column min-w-0 self-start print:hidden"
        desktop={desktop}
        width={editorWidth}
        min={EDITOR_MIN_WIDTH}
        max={editorMaxWidth}
        direction="right"
        label={messages.workspaceResizeEditor}
        onResizeStart={startResize}
        onResize={(width) => updateLiveWidth("editor", width)}
        onCommit={(width) => commit({ editorWidth: width })}
        onReset={() =>
          commit({
            editorWidth: Math.min(
              editorMaxWidth,
              getDefaultEditorWidth(containerWidth),
            ),
          })
        }
      >
        {editor}
      </ResizableWorkspacePanel>
      {preview}
      <ResizableWorkspacePanel
        className="workspace-agent-column min-w-0 self-start print:hidden"
        desktop={desktop}
        expanded={agentExpanded}
        width={agentWidth}
        min={AGENT_MIN_WIDTH}
        max={agentMaxWidth}
        direction="left"
        label={messages.workspaceResizeAgent}
        onResizeStart={startResize}
        onResize={(width) => updateLiveWidth("agent", width)}
        onCommit={(width) => commit({ agentWidth: width })}
        onReset={() =>
          commit({ agentWidth: Math.min(agentMaxWidth, DEFAULT_AGENT_WIDTH) })
        }
      >
        {agent}
      </ResizableWorkspacePanel>
    </div>
  );
}
