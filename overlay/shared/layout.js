// 整套画面的布局（1920×1080 画布）。后端把 config.yaml 的 overlay 段原样放进 status.layout，
// 这里只认 game 和 danmaku 两块，其余区域都由它们推算，保证各页面对齐。
export const CANVAS = { width: 1920, height: 1080 };
export const MARGIN = 24;
export const GAP = 18;
// 字幕右边给形象留出的宽度
export const AVATAR_ZONE = 400;

const DEFAULTS = {
  game: { left: 456, top: 24, width: 1440, height: 810 },
  danmaku: { left: 24, top: 282, width: 408, height: 774 },
};

function readRect(source, fallback) {
  const rect = { ...fallback };
  if (!source || typeof source !== 'object') return rect;
  for (const key of ['left', 'top', 'width', 'height']) {
    const value = Number(source[key]);
    if (Number.isFinite(value) && value >= 0 && value <= CANVAS.width) rect[key] = value;
  }
  return rect;
}

export function resolveLayout(layout) {
  const game = readRect(layout && layout.game, DEFAULTS.game);
  const danmaku = readRect(layout && layout.danmaku, DEFAULTS.danmaku);
  const statusTop = MARGIN;
  const subtitleTop = game.top + game.height + GAP + 4;
  return {
    game,
    danmaku,
    status: { left: danmaku.left, top: statusTop, width: danmaku.width, height: Math.max(120, danmaku.top - statusTop - GAP) },
    subtitle: {
      left: game.left,
      top: subtitleTop,
      width: Math.max(480, game.width - AVATAR_ZONE),
      height: Math.max(110, CANVAS.height - MARGIN - subtitleTop),
    },
  };
}

export function place(el, rect) {
  for (const key of ['left', 'top', 'width', 'height']) el.style[key] = `${rect[key]}px`;
}
