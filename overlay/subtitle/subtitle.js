import { connect } from '/shared/socket.js';
import { resolveLayout, place } from '/shared/layout.js';

const box = document.getElementById('box');
const text = document.getElementById('text');
const mood = document.getElementById('mood');
const ticker = document.getElementById('ticker');
const tickerText = document.getElementById('tickerText');

const MOODS = {
  happy: '开心 ♪', excited: '兴奋！', surprised: '诶？！', sad: '呜…', angry: '哼！',
  shy: '害羞 ///', smug: '得意 ω', confused: '疑惑 ？', cry: '哭哭 QAQ', pout: '鼓脸 ε',
  starry: '星星眼 ✧', dizzy: '晕乎乎 @@', playful: '略略略 ☆',
};

let active = null;
let timer = null;
let revealTimer = null;

function showIdle() {
  clearTimeout(timer);
  clearInterval(revealTimer);
  active = null;
  text.replaceChildren();
  mood.hidden = true;
  box.classList.remove('speaking');
  box.classList.add('idle');
}

function speak(d) {
  clearTimeout(timer);
  clearInterval(revealTimer);
  active = d.id;
  const chars = [...String(d.text || '')];
  text.classList.toggle('long', chars.length > 66);
  text.replaceChildren(...chars.map((c) => {
    const s = document.createElement('span');
    s.textContent = c;
    return s;
  }));
  const label = MOODS[d.emotion];
  mood.hidden = !label;
  if (label) mood.textContent = label;
  box.classList.remove('idle');
  box.classList.add('speaking');

  // 按语音时长逐字点亮，读到 85% 左右时全部显示
  const spans = text.children;
  const total = Number.isFinite(d.duration_s) && d.duration_s > 0 ? d.duration_s * 0.85 : chars.length * 0.12;
  const step = Math.max(20, (total * 1000) / Math.max(1, spans.length));
  let i = 0;
  revealTimer = setInterval(() => {
    if (i >= spans.length) { clearInterval(revealTimer); return; }
    spans[i].classList.add('on');
    i += 1;
  }, step);
  const timeout = Number.isFinite(d.timeout_s) ? d.timeout_s : 30;
  timer = setTimeout(showIdle, (timeout + 2) * 1000);
}

place(box, resolveLayout(null).subtitle);

connect((d) => {
  if (d.type === 'status') place(box, resolveLayout(d.layout).subtitle);
  if (d.type === 'speech') speak(d);
  if (d.type === 'speech_cancel' && d.id === active) showIdle();
  if (d.type === 'idle' && d.last_speech_id === active) showIdle();
}, {
  onConnection(online) {
    // 空闲时不放提示语：观众眼里只有大肥鱼本人，只在断线时说一声。
    ticker.hidden = online;
    if (online) return;
    showIdle();
    tickerText.textContent = '主播程序重连中…';
  },
});
