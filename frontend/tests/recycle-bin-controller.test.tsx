import { act, renderHook } from "@testing-library/react";
import {
  MemoryRouter,
  useLocation,
  useNavigate,
  useNavigationType,
} from "react-router-dom";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";
import { useRecycleBinActions } from "@/components/use-recycle-bin-actions";
import { useRecycleBinController } from "@/components/use-recycle-bin-controller";
import { useRecycleBinSelection } from "@/components/use-recycle-bin-selection";
import { createTrashProps } from "./helpers/route-view-fixtures";
import { deferred } from "./helpers/pdf-browser-fixtures";

it.each(["resume", "template"] as const)(
  "serializes %s actions and releases the lock after false, rejection, and success",
  async (kind) => {
    const props = createTrashProps();
    const restore = vi.fn<(...args: string[][]) => Promise<boolean>>();
    if (kind === "resume") props.onRestoreResume = restore;
    else props.onRestoreTemplate = restore;
    const { result } = renderHook(() => useRecycleBinActions(props));
    const start = () =>
      kind === "resume"
        ? result.current.restoreResumeIds(
            ["resume-0"],
            "resume-restore-selected",
          )
        : result.current.restoreTemplateIds(
            ["template-0"],
            "template-restore-selected",
          );
    for (const outcome of [false, "reject", true] as const) {
      const gate = deferred<boolean>();
      restore.mockReturnValueOnce(gate.promise);
      let first!: Promise<boolean>;
      let duplicate!: Promise<boolean>;
      act(() => {
        first = start();
        duplicate = start();
      });
      expect(result.current.isRunning()).toBe(true);
      expect(await duplicate).toBe(false);
      const settled = first.catch((error: unknown) => error);
      const error = new Error("Restore failed");
      await act(async () => {
        if (outcome === "reject") gate.reject(error);
        else gate.resolve(outcome);
        await settled;
      });
      expect(await settled).toBe(outcome === "reject" ? error : outcome);
      expect(result.current.isRunning()).toBe(false);
      expect(result.current.runningActionKey).toBeNull();
    }
    expect(restore).toHaveBeenCalledTimes(3);
    expect(restore).toHaveBeenLastCalledWith([`${kind}-0`]);
  },
);

it.each(["resume", "template"] as const)(
  "only clears selected %s IDs after successful restore or confirmed deletion",
  async (kind) => {
    const props = createTrashProps();
    const restore = vi.fn(async () => false);
    const remove = vi.fn(async () => false);
    if (kind === "resume") {
      props.onRestoreResume = restore;
      props.onDeleteResumeForever = remove;
    } else {
      props.onRestoreTemplate = restore;
      props.onDeleteTemplateForever = remove;
    }
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MemoryRouter
        initialEntries={[
          `/trash${kind === "template" ? "?tab=templates" : ""}`,
        ]}
      >
        {children}
      </MemoryRouter>
    );
    const { result } = renderHook(() => useRecycleBinController(props), {
      wrapper,
    });
    const selected = () =>
      kind === "resume" ? result.current.resumes : result.current.templates;
    act(() => selected().setSelectedIds([`${kind}-0`, `${kind}-6`, "unknown"]));
    expect(selected().selectedPageIds).toEqual([`${kind}-0`]);
    await act(async () => selected().restoreSelected());
    expect(selected().selectedPageIds).toEqual([`${kind}-0`]);
    restore.mockResolvedValueOnce(true);
    await act(async () => selected().restoreSelected());
    expect(selected().selectedPageIds).toEqual([]);
    act(() => {
      selected().setSelectedIds([`${kind}-1`]);
    });
    act(() => selected().deleteSelected());
    expect(result.current.dialog.pendingAction).toEqual({
      type: `${kind}-item`,
      ids: [`${kind}-1`],
    });
    await act(() => result.current.dialog.confirm());
    expect(selected().selectedPageIds).toEqual([`${kind}-1`]);
    expect(result.current.dialog.pendingAction).not.toBeNull();
    remove.mockResolvedValueOnce(true);
    await act(() => result.current.dialog.confirm());
    expect(remove).toHaveBeenLastCalledWith([`${kind}-1`]);
    expect(selected().selectedPageIds).toEqual([]);
    expect(result.current.dialog.pendingAction).toBeNull();
  },
);

it("clamps URL pages with replace and keeps selection bound to the visible page and existing IDs", async () => {
  const props = createTrashProps(13);
  let running = false;
  const wrapper = ({ children }: { children: ReactNode }) => (
    <MemoryRouter initialEntries={["/before", "/trash?page=99&keep=1"]}>
      {children}
    </MemoryRouter>
  );
  const { result, rerender } = renderHook(
    ({ deletedResumes }) => ({
      selection: useRecycleBinSelection({
        deletedResumes,
        deletedTemplates: props.deletedTemplates,
        isActionRunning: () => running,
      }),
      location: useLocation(),
      navigate: useNavigate(),
      navigationType: useNavigationType(),
    }),
    { wrapper, initialProps: { deletedResumes: props.deletedResumes } },
  );
  expect(result.current.selection.currentPage).toBe(3);
  expect(
    result.current.selection.paginatedDeletedResumes.map((item) => item.id),
  ).toEqual(["resume-12"]);
  expect(result.current.location.search).toBe("?page=3&keep=1");
  expect(result.current.navigationType).toBe("REPLACE");
  act(() =>
    result.current.selection.setSelectedResumeIds(["resume-12", "resume-0"]),
  );
  expect(result.current.selection.selectedResumePageIds).toEqual(["resume-12"]);
  rerender({ deletedResumes: props.deletedResumes.slice(0, 12) });
  expect(result.current.selection.currentPage).toBe(2);
  expect(result.current.selection.selectedResumePageIds).toEqual([]);
  expect(result.current.selection.paginatedDeletedResumes).toHaveLength(6);
  const key = result.current.location.key;
  act(() => {
    result.current.selection.changePage(2);
    result.current.selection.changePage(0);
    result.current.selection.changePage(100);
  });
  expect(result.current.location.key).toBe(key);
  running = true;
  act(() => result.current.selection.changePage(1));
  expect(result.current.location.key).toBe(key);
  running = false;
  act(() => result.current.selection.changePage(1));
  expect(result.current.location.search).toBe("?keep=1");
  act(() => result.current.selection.changeTab("templates"));
  expect(result.current.location.search).toBe("?keep=1&tab=templates");
  expect(result.current.selection.paginatedDeletedTemplates).toHaveLength(6);
  expect(result.current.selection.paginatedDeletedResumes).toEqual([]);
});
