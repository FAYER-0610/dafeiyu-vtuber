'use strict';
// 虚拟形象核心：唯一播放端（协议见 docs/websocket.md）+ 音量分析 + 调度渲染器。
// 画面由 video / layers / rig（WebGL 网格形象）渲染器负责，见 avatar.json。
// URL 参数：?debug 调试面板和快捷键；?offline 不连服务端，只预览动画；
//          ?pack= / ?renderer= 临时换包；?h= 角色高度；?x= / ?y= 脚底中心位置；?flip=1 水平翻转；
//          ?emotion= 先播一次表情；?talk 模拟说话。
(() => {
  const EMOTIONS = ['neutral', 'happy', 'excited', 'surprised', 'sad', 'angry', 'shy', 'smug', 'confused', 'cry', 'pout', 'starry', 'dizzy', 'playful'];
  const EMOTION_KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'q', 'w', 'e', 'r'];
  const DEFAULTS = {
    renderer: 'video',
    pack: 'packs/dsh-whale/pack.json',
    display: { charHeight: 560, anchorX: 1650, anchorY: 1060, flip: false, credit: true },
    motion: { breath: 1.0, sway: 1.0, talkBounce: 1.0 },
    mouthGain: 1.0,
  };

  const params = new URLSearchParams(location.search);
  const DEBUG = params.has('debug') || params.has('rigdebug');
  const OFFLINE = params.has('offline');
  const $ = (id) => document.getElementById(id);
  const stage = $('stage');
  const unlockBtn = $('unlock');
  const debugBox = $('debug');

  let cfg = DEFAULTS;
  let renderer = null;
  let level = 0;
  let fakeTalk = false;
  let emotion = 'neutral';
  let rendererError = '';
  let fakeSince = 0;
  let fakeVisemes = params.has('visemes');

  // ---------- 工具 ----------

  // 图形故障不得中断播放、ready 或 ACK；运行中失败只停渲染，不停音频。
  function renderError(err) {
    rendererError = err && err.message ? err.message : String(err);
    console.error('形象渲染失败', err);
    let box = document.getElementById('renderer-error');
    if (!box) { box = document.createElement('div'); box.id = 'renderer-error'; stage.appendChild(box); }
    box.textContent = `形象加载/渲染失败：${rendererError}（音频与播报确认仍可工作）`;
  }

  function renderCall(method, ...args) {
    if (!renderer || rendererError || typeof renderer[method] !== 'function') return;
    try { return renderer[method](...args); } catch (err) { renderError(err); }
  }

  // 协议数据均为 JSON；冻结副本，观察者不能污染播放器的原始消息。
  function readonlyCopy(value) {
    if (!value || typeof value !== 'object') return value;
    const copy = Array.isArray(value) ? value.map(readonlyCopy) : Object.fromEntries(Object.entries(value).map(([k, v]) => [k, readonlyCopy(v)]));
    return Object.freeze(copy);
  }

  function merge(base, over) {
    if (!over || typeof over !== 'object' || Array.isArray(over)) return over === undefined ? base : over;
    const out = { ...base };
    for (const [k, v] of Object.entries(over)) {
      out[k] = base && typeof base[k] === 'object' && !Array.isArray(base[k]) ? merge(base[k], v) : v;
    }
    return out;
  }

  function num(value, fallback) {
    const n = Number(value);
    return value !== null && value !== undefined && value !== '' && Number.isFinite(n) ? n : fallback;
  }

  async function fetchJson(url, options = {}) {
    const res = await fetch(url, { cache: 'no-store', ...options });
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
    return res.json();
  }

  // 只允许同目录下的相对路径，避免 URL 参数把页面指到别处
  const isLocalPath = (p) => typeof p === 'string' && /^[\w\-./]+$/.test(p) && !p.includes('..') && !p.startsWith('/');

  async function loadConfig() {
    try {
      cfg = merge(DEFAULTS, await fetchJson('avatar.json'));
    } catch (err) {
      console.error('avatar.json 读取失败，使用默认配置', err);
    }
    if (isLocalPath(params.get('pack'))) cfg.pack = params.get('pack');
    if (['video', 'layers', 'rig'].includes(params.get('renderer'))) cfg.renderer = params.get('renderer');
    const d = cfg.display;
    d.charHeight = num(params.get('h'), d.charHeight);
    d.anchorX = num(params.get('x'), d.anchorX);
    d.anchorY = num(params.get('y'), d.anchorY);
    if (params.has('flip')) d.flip = params.get('flip') !== '0';
  }

  // ---------- 音频 ----------

  const audio = new Audio();
  audio.preload = 'auto';
  let actx = null;
  let analyser = null;
  let samples = null;
  let audioReady = false;
  let manualRequired = false; // 服务端连续 ACK 超时后要求人工恢复
  let resetTimer = null;

  function ensureAudioGraph() {
    if (actx) return;
    actx = new (window.AudioContext || window.webkitAudioContext)();
    // 只接一条 destination：元素 → 分析器 → 输出，避免重音
    const source = actx.createMediaElementSource(audio);
    analyser = actx.createAnalyser();
    analyser.fftSize = 1024;
    samples = new Float32Array(analyser.fftSize);
    source.connect(analyser);
    analyser.connect(actx.destination);
    actx.onstatechange = () => {
      if (canAutoReady()) setAudioReady(true);
    };
  }

  function readLevel() {
    if (!analyser || audio.paused) return 0;
    analyser.getFloatTimeDomainData(samples);
    let sum = 0;
    for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
    return Math.sqrt(sum / samples.length);
  }

  function setAudioReady(ready, extra = {}) {
    audioReady = ready;
    unlockBtn.hidden = (ready && !manualRequired) || OFFLINE;
    send({ type: 'hello', role: 'avatar', ready, ...extra });
  }

  // 自动恢复只在音频环境正常、且服务端没要求人工处理时进行
  function canAutoReady() {
    return actx && actx.state === 'running' && !audioReady && !manualRequired;
  }

  unlockBtn.addEventListener('click', () => {
    ensureAudioGraph();
    actx.resume().then(() => {
      if (manualRequired) {
        manualRequired = false;
        unlockBtn.textContent = '点击启用声音';
        setAudioReady(true, { recovery: 'manual' });
      } else {
        setAudioReady(true);
      }
    }).catch(() => {});
  });

  // 服务端因 ACK 超时把本页设为未就绪：按 retry_after_s 自动重注册，或等待人工点击
  function onReadyReset(msg) {
    stopAudio();
    audioReady = false;
    clearTimeout(resetTimer);
    if (msg.manual_required) {
      manualRequired = true;
      unlockBtn.textContent = '主播语音已暂停，点击恢复';
      unlockBtn.hidden = OFFLINE;
      return;
    }
    const retry = num(msg.retry_after_s, null);
    if (retry !== null) {
      resetTimer = setTimeout(() => {
        if (canAutoReady()) setAudioReady(true);
      }, retry * 1000);
    }
  }

  // ---------- 播放 ----------

  let current = null; // { id, timer, done }

  function stopAudio() {
    const wasPlaying = Boolean(current);
    if (current) clearTimeout(current.timer);
    current = null;
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    if (wasPlaying && !fakeTalk) renderCall('speechEnd');
  }

  function finish(id, status) {
    if (!current || current.id !== id || current.done) return;
    current.done = true;
    send({ type: 'speech_done', id, status });
    stopAudio();
  }

  // 媒体错误（网络抖动、解码失败）：按协议回报 error 并 ready=false；
  // 直播时 OBS 里没人点按钮，所以音频环境正常的话 3 秒后自动重新 ready。
  function failPlayback(id, autoplayBlocked) {
    finish(id, 'error');
    setAudioReady(false);
    if (!autoplayBlocked) {
      setTimeout(() => {
        if (canAutoReady()) setAudioReady(true);
      }, 3000);
    }
  }

  function isRelativeAudioUrl(url) {
    return typeof url === 'string' && url.startsWith('/') && !url.startsWith('//');
  }

  function onSpeech(msg) {
    if (!active || msg.player_id !== clientId) return;
    if (typeof msg.id !== 'string' || !isRelativeAudioUrl(msg.audio_url)) return;
    stopAudio();
    emotion = EMOTIONS.includes(msg.emotion) ? msg.emotion : 'neutral';
    renderCall('speechStart', emotion, readonlyCopy(msg));

    const id = msg.id;
    const timeoutS = num(msg.timeout_s, num(msg.duration_s, 10) + 10);
    current = { id, done: false, speech: readonlyCopy(msg) };
    // 本地兜底：服务端超时会发 speech_cancel，这里只防止音频卡死
    current.timer = setTimeout(() => {
      if (current && current.id === id) stopAudio();
    }, (timeoutS + 1) * 1000);

    ensureAudioGraph();
    if (actx.state === 'suspended') actx.resume().catch(() => {});
    audio.src = msg.audio_url;
    audio.play().catch((err) => {
      if (current && current.id === id) failPlayback(id, err && err.name === 'NotAllowedError');
    });
  }

  audio.addEventListener('ended', () => {
    if (current) finish(current.id, 'ended');
  });
  audio.addEventListener('error', () => {
    if (current && audio.getAttribute('src')) failPlayback(current.id, false);
  });

  function showEmotion(e) {
    if (!EMOTIONS.includes(e)) return;
    emotion = e;
    renderCall('playEmotion', e);
  }

  // ---------- WebSocket ----------

  let ws = null;
  let clientId = null;
  let active = false;
  let backoff = 1000;
  let connState = 'offline';

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }

  function handle(msg) {
    switch (msg.type) {
      case 'hello':
        if (typeof msg.client_id === 'string') {
          clientId = msg.client_id;
          send({ type: 'hello', role: 'avatar', ready: audioReady });
        }
        break;
      case 'player':
        active = Boolean(msg.active) && msg.client_id === clientId;
        if (!active) stopAudio();
        break;
      case 'speech':
        onSpeech(msg);
        break;
      case 'speech_cancel':
        if (current && msg.id === current.id) stopAudio();
        break;
      case 'emotion':
        showEmotion(msg.emotion);
        break;
      case 'idle':
        emotion = EMOTIONS.includes(msg.emotion) ? msg.emotion : 'neutral';
        break;
      case 'ready_reset':
        onReadyReset(msg);
        break;
      default:
        break;
    }
    // 所有消息均可只读观察；唯一播放器与恢复流程仍由上面的协议分支负责。
    if (renderer && renderer.onMessage) renderCall('onMessage', readonlyCopy(msg));
  }

  function connect() {
    const scheme = location.protocol === 'https:' ? 'wss://' : 'ws://';
    connState = 'connecting';
    ws = new WebSocket(`${scheme}${location.host}/ws`);
    ws.onopen = () => {
      connState = 'open';
      backoff = 1000;
    };
    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg && typeof msg.type === 'string') handle(msg);
    };
    ws.onclose = () => {
      connState = 'closed';
      stopAudio();
      active = false;
      clientId = null;
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 15000);
    };
    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        // onclose 会负责重连
      }
    };
  }

  // ---------- 每帧 ----------

  function fakeLevel(t) {
    return Math.abs(Math.sin(t * 11)) * 0.16 + Math.abs(Math.sin(t * 3.3)) * 0.06;
  }

  function setFakeTalk(on) {
    fakeTalk = on;
    fakeSince = performance.now() / 1000;
    if (on) {
      const visemes = fakeVisemes ? Array.from({ length: 600 }, (_, i) => ({ t: i * 0.18, v: ['N', 'A', 'I', 'U', 'E', 'O'][i % 6] })) : undefined;
      renderCall('speechStart', emotion, { visemes });
    } else if (current) renderCall('speechStart', emotion, current.speech);
    else renderCall('speechEnd');
  }

  let lastDebug = -1;
  function updateDebug(t) {
    if (!DEBUG || (lastDebug >= 0 && t - lastDebug < 0.2)) return;
    lastDebug = t;
    debugBox.textContent = [
      `连接: ${OFFLINE ? '离线预览' : connState}  client: ${clientId || '-'}`,
      `播放器: ${active ? '是' : '否'}  ready: ${audioReady}${manualRequired ? '（需人工恢复）' : ''}  audio: ${actx ? actx.state : '-'}`,
      `渲染器: ${renderer ? renderer.kind : '-'}  情绪: ${emotion}  音量: ${level.toFixed(3)}`,
      rendererError || renderCall('debugInfo') || '',
      `当前语音: ${current ? current.id : '-'}`,
      '表情: 1-6 原表情  7 害羞  8 得意  9 疑惑  0 哭哭  Q 鼓脸  W 星星眼  E 晕乎乎  R 吐舌眨眼',
      '快捷键: Space 说话  V 时间戳/音量  I 空闲  B 眨眼（Shift 单左眼）  L 弹幕  T 思考  G 礼物  H 低血量',
    ].join('\n');
  }

  function frame(ms) {
    const t = ms / 1000;
    const raw = fakeTalk ? fakeLevel(t) : readLevel() * cfg.mouthGain;
    // 开口快、闭口慢，动作不会抖
    level += (raw - level) * (raw > level ? 0.6 : 0.25);
    renderCall('frame', t, level, {
      audioTime: fakeTalk ? (t - fakeSince) % 108 : audio.currentTime,
      speaking: fakeTalk || Boolean(current), paused: !fakeTalk && audio.paused,
      speechId: current ? current.id : null,
    });
    updateDebug(t);
    requestAnimationFrame(frame);
  }

  if (DEBUG) {
    debugBox.hidden = false;
    window.addEventListener('keydown', (e) => {
      if (e.repeat) return;
      const key = e.key.toLowerCase(), idx = EMOTION_KEYS.indexOf(key);
      if (idx >= 0 && idx < EMOTIONS.length) showEmotion(EMOTIONS[idx]);
      else if (e.code === 'Space') { e.preventDefault(); setFakeTalk(!fakeTalk); }
      else if (key === 'v') { fakeVisemes = !fakeVisemes; if (fakeTalk) setFakeTalk(true); }
      else if (key === 'i') renderCall('idleAction');
      else if (['b', 'l', 't', 'g', 'h'].includes(key) && renderer && renderer.debugAction) renderCall('debugAction', key, e.shiftKey);
      else if (key === 'b') renderCall('blink');
    });
  }

  // ---------- 启动 ----------

  (async () => {
    await loadConfig();
    const factory = (window.AvatarRenderers || {})[cfg.renderer];
    try {
      renderer = await factory(stage, cfg, { merge, num, fetchJson });
      renderCall('start');
    } catch (err) {
      renderError(err);
    }
    if (EMOTIONS.includes(params.get('emotion'))) emotion = params.get('emotion');
    if (params.has('talk')) setFakeTalk(true);
    else if (params.has('emotion')) showEmotion(emotion);
    if (!OFFLINE) {
      ensureAudioGraph();
      // OBS 浏览器源允许自动播放，音频环境会直接是 running；普通浏览器需要点一下按钮
      audioReady = actx.state === 'running';
      unlockBtn.hidden = audioReady;
      connect();
    }
    requestAnimationFrame(frame);
  })();
})();
