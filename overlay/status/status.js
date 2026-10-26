import { connect } from '/shared/socket.js';
import { resolveLayout, place } from '/shared/layout.js';

const $ = (id) => document.getElementById(id);
const card = $('card');

const SCREENS = {
  COMBAT: '战斗中', MAP: '选路线', REWARD: '领奖励', SHOP: '商店', FAKE_MERCHANT: '商店',
  EVENT: '事件', REST: '篝火', REST_SITE: '篝火', TREASURE: '宝箱', CHEST: '宝箱',
  CARD_SELECTION: '选牌', GAME_OVER: '本局结束', MAIN_MENU: '主菜单', CHARACTER_SELECT: '选角色',
};
const CHARACTERS = {
  IRONCLAD: '铁甲战士', SILENT: '静默猎手', DEFECT: '故障机器人', REGENT: '储君', NECROBINDER: '亡灵契约师',
};
const BILI = {
  connected: ['ok', '已连接'], connecting: ['warn', '接入中'], reconnecting: ['warn', '重连中'], disabled: ['', '未接入'],
};

function chip(id, lamp, text) {
  const el = $(id);
  el.querySelector('.lamp').className = `lamp ${lamp}`;
  el.querySelector('b').textContent = text;
}

function characterName(raw) {
  if (!raw) return null;
  const key = String(raw).replace(/^CHARACTER\./i, '').toUpperCase();
  return CHARACTERS[key] || String(raw);
}

function render(d) {
  place(card, resolveLayout(d.layout).status);
  const [title, ...rest] = String(d.banner || '大肥鱼的深海尖塔电台').split(' · ');
  $('title').textContent = title;
  $('tagline').textContent = rest.join(' · ') || 'AI 主播 · 杀戮尖塔2 实况';

  const live = $('live');
  live.className = 'live';
  if (d.mode === 'live') {
    live.classList.add('on');
    $('liveText').textContent = 'LIVE';
  } else {
    live.classList.add('rehearsal');
    $('liveText').textContent = d.mode === 'offline' ? '离线测试' : '彩排中';
  }

  const g = d.game || {};
  chip('chip-game', d.game_online ? 'ok' : 'bad', d.game_online ? '在线' : '离线');
  chip('chip-team', g.teammate_online ? 'ok' : '', g.teammate_online ? (g.play_running ? '思考中' : '待命') : '离线');
  const [lamp, text] = d.mode === 'live' ? (BILI[d.bilibili] || ['warn', '等待中']) : ['warn', '模拟'];
  chip('chip-bili', lamp, text);
  chip('chip-voice', d.speaking ? 'ok pulse' : d.avatar_ready ? 'ok' : 'warn', d.speaking ? '说话中' : d.avatar_ready ? '就绪' : '等待形象');

  // OBS 里游戏画面加了延迟时，局面信息也晚同样秒数再显示，免得比画面先变。
  const delay = Math.max(0, Math.min(30, Number((d.layout || {}).game_delay_seconds) || 0));
  if (delay) setTimeout(() => renderRun(g), delay * 1000);
  else renderRun(g);
}

function renderRun(g) {
  const name = characterName(g.character);
  $('character').textContent = name || '等待开局';
  $('floor').textContent = Number.isFinite(g.floor) ? `第 ${g.floor} 层` : '';
  const screen = $('screen');
  const screenText = SCREENS[g.screen];
  screen.hidden = !screenText;
  if (screenText) {
    screen.textContent = g.screen === 'COMBAT' && Number.isFinite(g.turn) ? `${screenText} · 回合 ${g.turn}` : screenText;
    screen.classList.toggle('combat', g.screen === 'COMBAT');
  }

  const hp = $('hp');
  const ok = Number.isFinite(g.hp) && Number.isFinite(g.max_hp) && g.max_hp > 0;
  const ratio = ok ? Math.max(0, Math.min(1, g.hp / g.max_hp)) : 0;
  $('hpFill').style.width = `${(ratio * 100).toFixed(1)}%`;
  $('hpText').textContent = ok ? `${g.hp} / ${g.max_hp}` : '— / —';
  hp.classList.toggle('empty', !ok);
  hp.classList.toggle('low', ok && ratio <= 0.3);
}

place(card, resolveLayout(null).status);
connect((d) => {
  if (d.type === 'status') render(d);
}, {
  onConnection(online) {
    if (online) return;
    const live = $('live');
    live.className = 'live';
    $('liveText').textContent = '重连中';
    chip('chip-game', 'bad', '主播离线');
    chip('chip-team', '', '未知');
    chip('chip-bili', 'warn', '等待重连');
    chip('chip-voice', 'bad', '断开');
  },
});
