export const editorSortingMessages = {
  en: {
    role: "sortable heading",
    instructions:
      "Press Space to start sorting, use the up and down arrow keys to move, then press Space to drop or Escape to cancel. Move up and move down buttons are also available. Use the expand or collapse button to show or hide the content.",
    started: (label: string) => `Picked up ${label}.`,
    moved: (position: number, count: number) =>
      `Position ${position} of ${count}.`,
    dropped: (label: string, position: number, count: number) =>
      `Placed ${label} at position ${position} of ${count}.`,
    cancelled: "Sorting cancelled.",
  },
  zh: {
    role: "可排序标题",
    instructions:
      "按空格开始排序，使用上下方向键移动，再按空格放置或按 Escape 取消。也可以使用上移和下移按钮。展开和收起内容请使用右侧按钮。",
    started: (label: string) => `已拾起${label}`,
    moved: (position: number, count: number) =>
      `第 ${position} 项，共 ${count} 项`,
    dropped: (label: string, position: number, count: number) =>
      `已将${label}放到第 ${position} 项，共 ${count} 项`,
    cancelled: "已取消排序",
  },
};
