import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { loadResumeFontStyles } from "@/components/preview/resume-font-loader";
import { useResumeThumbnailFonts } from "@/components/preview/resume-thumbnail-fonts";
import type { ResumeFontFamily } from "@/types/resume";

vi.mock("@/components/preview/resume-font-loader", () => ({
  loadResumeFontStyles: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(loadResumeFontStyles).mockReset().mockResolvedValue(undefined);
});

describe("Thumbnail collection fonts", () => {
  it.each<{ fonts: ResumeFontFamily[]; requested: ResumeFontFamily[] }>([
    { fonts: ["times"], requested: ["serif"] },
    { fonts: ["times", "serif", "inter"], requested: ["inter", "serif"] },
    { fonts: [], requested: [] },
  ])(
    "loads the required script fonts once for $fonts",
    ({ fonts, requested }) => {
      renderHook(() => useResumeThumbnailFonts(fonts));
      expect(vi.mocked(loadResumeFontStyles).mock.calls).toEqual(
        requested.map((font) => [font]),
      );
    },
  );

  it("does not reload unchanged script requirements when the collection rerenders", () => {
    const hook = renderHook(({ fonts }) => useResumeThumbnailFonts(fonts), {
      initialProps: { fonts: ["inter", "serif"] as ResumeFontFamily[] },
    });
    hook.rerender({ fonts: ["times", "noto_sans_sc", "plex", "serif"] });
    hook.rerender({ fonts: ["serif", "inter", "inter"] });
    expect(vi.mocked(loadResumeFontStyles).mock.calls).toEqual([
      ["inter"],
      ["serif"],
    ]);
  });

  it("loads newly required fonts as visible thumbnails change", () => {
    const hook = renderHook(({ fonts }) => useResumeThumbnailFonts(fonts), {
      initialProps: { fonts: [] as ResumeFontFamily[] },
    });
    expect(loadResumeFontStyles).not.toHaveBeenCalled();
    hook.rerender({ fonts: ["times"] });
    expect(loadResumeFontStyles).toHaveBeenCalledExactlyOnceWith("serif");
    hook.rerender({ fonts: ["plex"] });
    expect(vi.mocked(loadResumeFontStyles).mock.calls).toEqual([
      ["serif"],
      ["inter"],
    ]);
    hook.rerender({ fonts: [] });
    expect(loadResumeFontStyles).toHaveBeenCalledTimes(2);
  });

  it("handles a stylesheet rejection after the collection unmounts", async () => {
    let rejectStyles: (error: Error) => void = () => {};
    vi.mocked(loadResumeFontStyles).mockReturnValueOnce(
      new Promise((_, reject) => {
        rejectStyles = reject;
      }),
    );
    const hook = renderHook(() => useResumeThumbnailFonts(["inter"]));
    hook.unmount();
    await act(async () => rejectStyles(new Error("Stylesheet unavailable")));
    expect(loadResumeFontStyles).toHaveBeenCalledOnce();
  });
});
