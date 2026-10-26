import { connect } from '/shared/socket.js';

const $ = (id) => document.getElementById(id);
let since = null;

function render(stream, online) {
  const live = online && stream && stream.live;
  $('lamp').className = `lamp ${online ? (live ? 'ok pulse' : '') : 'bad'}`;
  $('state').textContent = online ? (live ? '直播中' : '未开播') : '主播程序没连上';
  $('start').disabled = !online || live;
  $('end').disabled = !online || !live;
  since = live ? new Date(stream.since) : null;
  if (stream) {
    $('diary').textContent = stream.diary ? `memory\\${stream.diary.replace('/', '\\')}` : '—';
    $('dynamic').textContent = stream.dynamic || '—';
  }
  tick();
}

function tick() {
  if (!since || Number.isNaN(since.getTime())) { $('since').textContent = ''; return; }
  const minutes = Math.max(0, Math.floor((Date.now() - since.getTime()) / 60000));
  $('since').textContent = `已经播了 ${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`;
}
setInterval(tick, 30000);

async function send(action) {
  if (action === 'end' && !window.confirm('确定下播？她会先道别，然后整理记忆、写日记、发动态。')) return;
  $('start').disabled = $('end').disabled = true;
  try {
    await fetch('/api/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }) });
  } catch { /* 状态以服务器推送为准 */ }
}
$('start').addEventListener('click', () => send('start'));
$('end').addEventListener('click', () => send('end'));

async function fake(kind) {
  const name = $('name').value.trim() || '测试观众';
  const text = $('text').value.trim();
  if (kind === 'danmaku' && !text) return;
  const r = await fetch('/api/test-chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, name, text: kind === 'gift' ? '' : text }) }).catch(() => null);
  const li = document.createElement('li');
  li.textContent = r && r.ok ? `${name}：${kind === 'enter' ? '（进场）' : kind === 'gift' ? '（送礼）' : text}` : '发送失败，主播程序要用 --manual-chat 启动';
  $('log').prepend(li);
  if (kind === 'danmaku') $('text').value = '';
}
$('say').addEventListener('click', () => fake('danmaku'));
$('enter').addEventListener('click', () => fake('enter'));
$('gift').addEventListener('click', () => fake('gift'));
$('text').addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) fake('danmaku'); });

let online = false;
connect((d) => { if (d.type === 'status') { $('test').hidden = !d.manual_chat; render(d.stream, online); } },
  { onConnection: (ok) => { online = ok; render(null, ok); } });
