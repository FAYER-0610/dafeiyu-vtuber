import { connect } from '/shared/socket.js';
import { CANVAS, resolveLayout, place } from '/shared/layout.js';

const ocean = document.getElementById('ocean');
const frame = document.getElementById('frame');
const RADIUS = 14;

// 用偶奇填充把游戏区域从背景里挖成圆角透明洞
function applyLayout(layout) {
  const { game: g } = resolveLayout(layout);
  const r = RADIUS;
  const right = g.left + g.width;
  const bottom = g.top + g.height;
  const hole = `M${g.left + r} ${g.top} H${right - r} A${r} ${r} 0 0 1 ${right} ${g.top + r} V${bottom - r} A${r} ${r} 0 0 1 ${right - r} ${bottom} H${g.left + r} A${r} ${r} 0 0 1 ${g.left} ${bottom - r} V${g.top + r} A${r} ${r} 0 0 1 ${g.left + r} ${g.top} Z`;
  ocean.style.clipPath = `path(evenodd, "M0 0 H${CANVAS.width} V${CANVAS.height} H0 Z ${hole}")`;
  place(frame, g);
}

function spawnBubbles(count) {
  const box = document.getElementById('bubbles');
  for (let i = 0; i < count; i += 1) {
    const b = document.createElement('span');
    b.className = 'bubble';
    const size = 6 + Math.random() * 16;
    b.style.width = `${size}px`;
    b.style.height = `${size}px`;
    b.style.left = `${Math.random() * 100}%`;
    b.style.animationDuration = `${14 + Math.random() * 16}s`;
    b.style.animationDelay = `${-Math.random() * 30}s`;
    box.appendChild(b);
  }
}

applyLayout(null);
spawnBubbles(22);
connect((d) => {
  if (d.type === 'status') applyLayout(d.layout);
});
