'use strict';
// 分层图片包渲染器：底图 + 眼睛 + 嘴巴叠加，音量驱动嘴型，自动眨眼、呼吸、表情动作和头顶特效。
(() => {
  const R = (window.AvatarRenderers = window.AvatarRenderers || {});
  const DEFAULTS = {
    mouth: { halfLevel: 0.05, openLevel: 0.13 },
    blink: { minGap: 2.2, maxGap: 5.5, closedMs: 110, doubleChance: 0.18 },
  };

  const FX_SVG = {
    sparkle: '<svg viewBox="0 0 40 40" width="100%" height="100%"><path d="M20 0 L24 16 L40 20 L24 24 L20 40 L16 24 L0 20 L16 16 Z" fill="#ffe27a"/></svg>',
    bang: '<svg viewBox="0 0 30 60" width="100%" height="100%"><path d="M9 2 H21 L18 40 H12 Z" fill="#ff5a5a"/><circle cx="15" cy="52" r="6" fill="#ff5a5a"/></svg>',
    drop: '<svg viewBox="0 0 30 44" width="100%" height="100%"><path d="M15 0 C22 14 30 22 30 30 A15 14 0 0 1 0 30 C0 22 8 14 15 0 Z" fill="#8fd3ff"/></svg>',
    anger: '<svg viewBox="0 0 40 40" width="100%" height="100%"><g stroke="#ff3b3b" stroke-width="6" stroke-linecap="round" fill="none"><path d="M6 14 Q14 14 14 6"/><path d="M26 6 Q26 14 34 14"/><path d="M34 26 Q26 26 26 34"/><path d="M14 34 Q14 26 6 26"/></g></svg>',
  };

  // 位置是相对角色画布的百分比，大致在头顶周围
  const EMOTION_FX = {
    happy: [['sparkle', 78, 14, 7]],
    excited: [['sparkle', 80, 12, 8], ['sparkle', 14, 20, 5]],
    surprised: [['bang', 80, 8, 6]],
    sad: [['drop', 76, 30, 5]],
    angry: [['anger', 76, 14, 8]],
  };

  const decay = (since, dur) => (since < dur ? 1 - since / dur : 0);
  const bump = (since, dur) => (since < dur ? Math.sin((Math.PI * since) / dur) : 0);

  R.layers = async function createLayersRenderer(stage, cfg, util) {
    const pack = util.merge(DEFAULTS, await util.fetchJson(cfg.pack));
    const base = cfg.pack.replace(/[^/]*$/, '');
    const c = pack.canvas;
    const d = cfg.display;
    const s = d.charHeight / c.charHeight;

    const rig = document.createElement('div');
    rig.className = 'rig';
    rig.style.width = `${c.width * s}px`;
    rig.style.height = `${c.height * s}px`;
    rig.style.left = `${d.anchorX - c.anchorX * s}px`;
    rig.style.top = `${d.anchorY - c.anchorY * s}px`;
    if (d.flip) rig.style.transform = 'scaleX(-1)';
    const body = document.createElement('div');
    body.className = 'rig-body';
    const fx = document.createElement('div');
    fx.className = 'rig-fx';
    rig.append(body, fx);
    stage.appendChild(rig);

    // 每个图层把用到的差分各建一个 <img>，切换只改 .on，不重新解码。
    function makePart() {
      const container = document.createElement('div');
      container.className = 'layer';
      body.appendChild(container);
      const imgs = new Map();
      let shown = null;
      return {
        preload(src) {
          if (!src || imgs.has(src)) return;
          const img = document.createElement('img');
          img.alt = '';
          img.decoding = 'sync';
          img.src = base + src;
          container.appendChild(img);
          imgs.set(src, img);
        },
        show(src) {
          if (src === shown) return;
          if (src) this.preload(src);
          if (shown && imgs.has(shown)) imgs.get(shown).classList.remove('on');
          if (src) imgs.get(src).classList.add('on');
          shown = src;
        },
      };
    }

    const parts = { base: makePart(), eyes: makePart(), mouth: makePart() };
    const st = { emotion: 'neutral', emotionSince: 0, mouth: 'closed', blinkUntil: 0, nextBlink: 0, secondBlinkAt: 0, now: 0 };

    function layerSrc(part, key) {
      const over = pack.emotions[st.emotion] || {};
      if (part === 'base') return over.base || pack.layers.base;
      const fromEmotion = over[part] && over[part][key];
      const fromDefault = pack.layers[part] && pack.layers[part][key];
      if (fromEmotion || fromDefault) return fromEmotion || fromDefault;
      // 没有"半张嘴"素材时退回张嘴
      if (part === 'mouth' && key === 'half') return layerSrc('mouth', 'open');
      return null;
    }

    for (const set of [pack.layers, ...Object.values(pack.emotions || {})]) {
      parts.base.preload(set.base);
      for (const src of Object.values(set.eyes || {})) parts.eyes.preload(src);
      for (const src of Object.values(set.mouth || {})) parts.mouth.preload(src);
    }

    function spawnFx(emotion) {
      for (const [kind, x, y, size] of EMOTION_FX[emotion] || []) {
        const item = document.createElement('div');
        item.className = 'fx-item';
        item.style.left = `${x}%`;
        item.style.top = `${y}%`;
        item.style.width = `${size}%`;
        item.style.aspectRatio = '1';
        item.innerHTML = FX_SVG[kind]; // 固定的内置 SVG，不含任何外部输入
        fx.appendChild(item);
        setTimeout(() => item.remove(), 1700);
      }
    }

    function setEmotion(emotion) {
      st.emotion = emotion;
      st.emotionSince = st.now;
      spawnFx(emotion);
    }

    function scheduleBlink(t) {
      const b = pack.blink;
      st.nextBlink = t + b.minGap + Math.random() * (b.maxGap - b.minGap);
    }

    function updateMouth(level) {
      const { halfLevel: half, openLevel: open } = pack.mouth;
      let mouth = st.mouth;
      if (level >= open) mouth = 'open';
      else if (level >= half) mouth = mouth === 'open' && level > open * 0.8 ? 'open' : 'half';
      else if (level < half * 0.7) mouth = 'closed';
      st.mouth = mouth;
    }

    function updateBlink(t) {
      if (t >= st.nextBlink) {
        st.blinkUntil = t + pack.blink.closedMs / 1000;
        if (Math.random() < pack.blink.doubleChance) st.secondBlinkAt = t + 0.25;
        scheduleBlink(t);
      }
      if (st.secondBlinkAt && t >= st.secondBlinkAt) {
        st.blinkUntil = t + pack.blink.closedMs / 1000;
        st.secondBlinkAt = 0;
      }
    }

    function updatePose(t, level) {
      const m = cfg.motion;
      const since = t - st.emotionSince;
      const breath = Math.sin((t * 2 * Math.PI) / 3.4) * m.breath;
      let tx = 0;
      let ty = -Math.min(level * 120, 14) * m.talkBounce;
      let rot = 0.8 * Math.sin((t * 2 * Math.PI) / 6.1) * m.sway;
      let sx = 1 - 0.004 * breath;
      let sy = 1 + 0.01 * breath;
      if (level >= pack.mouth.halfLevel) rot += 1.2 * Math.sin(t * 9) * m.talkBounce;

      switch (st.emotion) {
        case 'happy':
          ty -= Math.abs(Math.sin(t * 4)) * 6 * decay(since, 2);
          break;
        case 'excited':
          ty -= Math.abs(Math.sin(t * 6.5)) * 12 * decay(since, 2.5);
          break;
        case 'surprised': {
          const b = bump(since, 0.35);
          ty -= 26 * b;
          sx *= 1 + 0.03 * b;
          sy *= 1 + 0.03 * b;
          break;
        }
        case 'sad':
          ty += 8;
          rot -= 2;
          sy *= 0.99;
          break;
        case 'angry':
          tx += Math.sin(t * 60) * 6 * decay(since, 0.6);
          break;
        default:
          break;
      }
      body.style.transform = `translate(${tx.toFixed(2)}px, ${ty.toFixed(2)}px) rotate(${rot.toFixed(3)}deg) scale(${sx.toFixed(4)}, ${sy.toFixed(4)})`;
    }

    return {
      kind: 'layers',
      start() {
        scheduleBlink(st.now);
      },
      speechStart(emotion) {
        setEmotion(emotion);
      },
      speechEnd() {},
      playEmotion(emotion) {
        setEmotion(emotion);
      },
      blink() {
        st.nextBlink = 0;
      },
      frame(t, level) {
        st.now = t;
        updateMouth(level);
        updateBlink(t);
        parts.base.show(layerSrc('base'));
        parts.eyes.show(layerSrc('eyes', t < st.blinkUntil ? 'closed' : 'open'));
        parts.mouth.show(layerSrc('mouth', st.mouth));
        updatePose(t, level);
      },
      debugInfo() {
        return `表情: ${st.emotion}  嘴型: ${st.mouth}`;
      },
    };
  };
})();
