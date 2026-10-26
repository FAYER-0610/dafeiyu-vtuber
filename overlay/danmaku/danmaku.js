import { connect } from '/shared/socket.js';
import { resolveLayout, place } from '/shared/layout.js';

const chat = document.getElementById('chat');
const list = document.getElementById('messages');
const empty = document.getElementById('empty');
const connection = document.getElementById('connection');
const connLamp = document.getElementById('connLamp');
const MAX_ITEMS = 18;
const BILI = {
  connected: ['ok', '已连接'], connecting: ['warn', '接入中'], reconnecting: ['warn', '重连中'], disabled: ['', '未接入'],
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

// 头像只接受 B 站 https 图床，其余用名字首字
function avatar(item) {
  const fallback = (item.name || '鲸').slice(0, 1);
  const box = el('div', 'av', fallback);
  if (!item.avatar) return box;
  try {
    const u = new URL(item.avatar);
    if (u.protocol === 'https:' && u.hostname.endsWith('.hdslb.com')) {
      const img = el('img');
      img.src = u.href;
      img.alt = '';
      img.referrerPolicy = 'no-referrer';
      img.addEventListener('error', () => { box.textContent = fallback; });
      box.replaceChildren(img);
    }
  } catch { /* 无效链接用首字 */ }
  return box;
}

function medal(m) {
  if (!m || !m.name) return null;
  const level = Number(m.level) || 0;
  const tier = Math.min(6, Math.max(1, Math.ceil(level / 4)));
  const box = el('span', `medal t${tier}`);
  box.append(el('span', '', m.name), el('b', '', String(level)));
  return box;
}

function clock(t) {
  return new Date(t * 1000).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false });
}

function build(item) {
  const card = el('article', 'msg');
  card.dataset.id = item.id;
  card.dataset.kind = item.kind;

  if (item.kind === 'enter') {
    card.append(el('span', 'gem'), el('b', '', item.name || ''), el('span', '', item.text || '游进了直播间'));
    return card;
  }

  if (item.kind === 'sc' || item.kind === 'guard') {
    card.classList.add('card-like');
    const head = el('div', 'head');
    head.append(avatar(item), el('span', 'name', item.name || ''));
    const m = medal(item.medal);
    if (m) head.append(m);
    head.append(el('span', 'badge', item.kind === 'sc' ? '醒目留言' : '上舰'));
    card.append(head, el('p', 'text', item.text || ''));
    return card;
  }

  const body = el('div', 'body');
  const meta = el('div', 'meta');
  meta.append(el('span', 'name', item.name || ''));
  const m = medal(item.medal);
  if (m) meta.append(m);
  if (item.kind === 'gift') meta.append(el('span', 'badge', '礼物'));
  if (Number.isFinite(item.time)) meta.append(el('time', 'time', clock(item.time)));
  body.append(meta, el('p', 'text', item.text || ''));
  card.append(avatar(item), body);
  return card;
}

function refreshEmpty() {
  empty.hidden = list.children.length > 0;
}

function add(item) {
  if (!item || !item.id) return;
  if ([...list.children].some((n) => n.dataset.id === item.id)) return;
  list.append(build(item));
  while (list.children.length > MAX_ITEMS) list.firstElementChild.remove();
  refreshEmpty();
}

function remove(ids) {
  for (const n of [...list.children]) {
    if (!ids.includes(n.dataset.id)) continue;
    n.classList.add('leaving');
    setTimeout(() => { n.remove(); refreshEmpty(); }, 300);
  }
}

function setConnection(lamp, text) {
  connLamp.className = `lamp ${lamp}`;
  connection.textContent = text;
}

place(chat, resolveLayout(null).danmaku);
connect((d) => {
  if (d.type === 'danmaku') add(d.item);
  if (d.type === 'history') {
    list.replaceChildren();
    (d.items || []).slice(-MAX_ITEMS).forEach(add);
    refreshEmpty();
  }
  if (d.type === 'danmaku_delete') remove(d.ids || []);
  if (d.type === 'status') {
    place(chat, resolveLayout(d.layout).danmaku);
    if (d.mode === 'live') setConnection(...(BILI[d.bilibili] || ['warn', '等待中']));
    else setConnection('warn', '模拟弹幕');
  }
}, {
  onConnection(online) {
    if (online) return;
    setConnection('bad', '正在重连');
    list.replaceChildren();
    refreshEmpty();
  },
});
