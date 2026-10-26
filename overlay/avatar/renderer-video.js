'use strict';
// 视频动画包渲染器：两个 <video> 交替淡入淡出，播放 pack.json 里的透明 webm 片段。
// 整段视频没有分层的嘴，说话时播"碎碎念"类片段，并随音量轻微弹动。
(() => {
  const R = (window.AvatarRenderers = window.AvatarRenderers || {});
  const FADE_MS = 180;
  const LOAD_TIMEOUT_MS = 4000;

  R.video = async function createVideoRenderer(stage, cfg, util) {
    const pack = await util.fetchJson(cfg.pack);
    const base = cfg.pack.replace(/[^/]*$/, '');
    const v = pack.video;
    const clips = pack.clips;
    const d = cfg.display;
    const s = d.charHeight / v.charHeight;

    const wrap = document.createElement('div');
    wrap.className = 'video-wrap';
    wrap.style.width = `${v.width * s}px`;
    wrap.style.height = `${v.height * s}px`;
    wrap.style.left = `${d.anchorX - v.anchorX * s}px`;
    wrap.style.top = `${d.anchorY - v.anchorY * s}px`;
    wrap.style.transformOrigin = `${v.anchorX * s}px ${v.anchorY * s}px`;
    stage.appendChild(wrap);

    if (d.credit && pack.credit) {
      const credit = document.createElement('div');
      credit.className = 'credit';
      credit.textContent = pack.credit;
      stage.appendChild(credit);
    }

    const slots = [0, 1].map(() => {
      const el = document.createElement('video');
      el.muted = true;
      el.playsInline = true;
      el.preload = 'auto';
      el.className = 'clip';
      wrap.appendChild(el);
      return el;
    });
    let front = 0;
    let seq = 0;
    let current = { name: null, kind: 'none' };
    let speaking = false;
    let nextIdleAction = 0;
    let now = 0;
    let bounce = 0;
    const lastPick = new Map();

    const clipUrl = (name) => `${base}clips/${encodeURIComponent(name)}.webm`;

    function pick(list, key) {
      if (!list || list.length === 0) return null;
      if (list.length === 1) return list[0];
      let choice;
      do {
        choice = list[Math.floor(Math.random() * list.length)];
      } while (choice === lastPick.get(key));
      lastPick.set(key, choice);
      return choice;
    }

    function waitReady(el) {
      return new Promise((resolve) => {
        if (el.readyState >= 3) return resolve(true);
        const done = (ok) => {
          clearTimeout(timer);
          el.removeEventListener('canplay', onReady);
          el.removeEventListener('error', onError);
          resolve(ok);
        };
        const onReady = () => done(true);
        const onError = () => done(false);
        const timer = setTimeout(() => done(false), LOAD_TIMEOUT_MS);
        el.addEventListener('canplay', onReady);
        el.addEventListener('error', onError);
      });
    }

    // 在后台槽位加载新片段，就绪后淡入；更新的请求会作废旧请求。
    async function play(name, kind, loop) {
      if (!name) return;
      const token = ++seq;
      const back = slots[1 - front];
      back.loop = loop;
      back.src = clipUrl(name);
      const ok = await waitReady(back);
      if (token !== seq) return;
      if (!ok) {
        console.warn('片段加载失败', name);
        if (kind !== 'idle') scheduleAfterClip();
        return;
      }
      back.currentTime = 0;
      try {
        await back.play();
      } catch (err) {
        console.warn('片段播放失败', name, err);
      }
      if (token !== seq) return;
      const old = slots[front];
      back.classList.add('on');
      old.classList.remove('on');
      front = 1 - front;
      current = { name, kind };
      setTimeout(() => {
        if (slots[1 - front] === old) old.pause();
      }, FADE_MS + 40);
    }

    function playIdle() {
      scheduleIdleAction();
      play(pick(clips.idle, 'idle'), 'idle', true);
    }

    function playTalk() {
      play(pick(clips.talk, 'talk'), 'talk', true);
    }

    function scheduleIdleAction() {
      const [lo, hi] = pack.idleActionGap || [25, 60];
      nextIdleAction = now + lo + Math.random() * (hi - lo);
    }

    // 一次性片段（表情、空闲小动作）播完后：还在说话就接碎碎念，否则回待机
    function scheduleAfterClip() {
      if (speaking) playTalk();
      else playIdle();
    }

    for (const el of slots) {
      el.addEventListener('ended', () => {
        if (el === slots[front] && !el.loop) scheduleAfterClip();
      });
    }

    function emotionClip(emotion) {
      return emotion && emotion !== 'neutral' ? pick(clips.emotions && clips.emotions[emotion], emotion) : null;
    }

    return {
      kind: 'video',
      start() {
        playIdle();
      },
      speechStart(emotion) {
        speaking = true;
        const clip = emotionClip(emotion);
        if (clip) play(clip, 'emotion', false);
        else if (current.kind !== 'talk') playTalk();
      },
      speechEnd() {
        speaking = false;
        // 表情片段让它自然播完（播完会回待机）；碎碎念循环立即收尾
        if (current.kind === 'talk') playIdle();
      },
      playEmotion(emotion) {
        const clip = emotionClip(emotion);
        if (clip) play(clip, 'emotion', false);
      },
      idleAction() {
        if (!speaking) play(pick(clips.idleActions, 'idleActions'), 'idleAction', false);
      },
      frame(t, level) {
        now = t;
        if (!speaking && current.kind === 'idle' && nextIdleAction && t >= nextIdleAction) {
          nextIdleAction = 0;
          play(pick(clips.idleActions, 'idleActions'), 'idleAction', false);
        }
        // 音量驱动的轻微弹动，代替嘴型
        const target = Math.min(level * 90, 9) * (cfg.motion.talkBounce ?? 1);
        bounce += (target - bounce) * (target > bounce ? 0.5 : 0.2);
        const sc = 1 + bounce / 600;
        wrap.style.transform = `translateY(${(-bounce).toFixed(2)}px) scale(${d.flip ? -sc : sc}, ${sc})`;
      },
      debugInfo() {
        const slot = (el, i) => `${i === front ? '前' : '后'}[rs${el.readyState} ns${el.networkState}${el.error ? ` err${el.error.code}` : ''}${el.paused ? ' 暂停' : ' 播放'}]`;
        return `片段: ${current.name || '-'}（${current.kind}）  ${slots.map(slot).join(' ')}`;
      },
    };
  };
})();
