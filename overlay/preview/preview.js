'use strict';
// 按 OBS 里的叠放顺序把各页面叠起来：舞台背景 → 状态 → 弹幕 → 字幕 → 形象
// 加 ?avatar 才叠形象页；其余查询参数（如 renderer=rig&pack=...&debug）原样转给形象页
const params = new URLSearchParams(location.search);
const pages = ['stage', 'status', 'danmaku', 'subtitle'];
if (params.has('avatar')) pages.push('avatar');
params.delete('avatar');
const avatarQuery = params.toString();
let avatarFrame = null;
for (const name of pages) {
  const frame = document.createElement('iframe');
  frame.src = `/overlay/${name}/${name === 'avatar' && avatarQuery ? `?${avatarQuery}` : ''}`;
  frame.allow = 'autoplay';
  document.body.appendChild(frame);
  if (name === 'avatar') avatarFrame = frame;
}

// 键盘焦点在本页时，把按键转给形象页（形象页的 debug 快捷键监听在它自己的 window 上）
window.addEventListener('keydown', (e) => {
  if (!avatarFrame || !avatarFrame.contentWindow) return;
  if (e.code === 'Space') e.preventDefault();
  const Ev = avatarFrame.contentWindow.KeyboardEvent;
  avatarFrame.contentWindow.dispatchEvent(new Ev('keydown', { key: e.key, code: e.code, shiftKey: e.shiftKey, repeat: e.repeat }));
});
