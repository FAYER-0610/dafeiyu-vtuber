'use strict';
// 自研 WebGL1 分层网格：局部网格变形 + 组变换 + 二阶弹簧链；无第三方依赖。
(() => {
  const R = (window.AvatarRenderers = window.AvatarRenderers || {});
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const rad = Math.PI / 180;
  const rand = (a, b) => a + Math.random() * (b - a);
  const own = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const finite = (x) => typeof x === 'number' && Number.isFinite(x);
  const IDENTITY = [1, 0, 0, 1, 0, 0];
  const DEFAULTS = {
    parameters: {
      yaw: { min: -1, max: 1, value: 0 }, pitch: { min: -1, max: 1, value: 0 }, roll: { min: -1, max: 1, value: 0 },
      gazeX: { min: -1, max: 1, value: 0 }, gazeY: { min: -1, max: 1, value: 0 },
      eyeLeft: { min: 0, max: 1, value: 1 }, eyeRight: { min: 0, max: 1, value: 1 },
      brow: { min: -1, max: 1, value: 0 }, browLeft: { min: -1, max: 1, value: 0 }, browRight: { min: -1, max: 1, value: 0 },
      cheekPuff: { min: 0, max: 1, value: 0 }, blush: { min: 0, max: 1, value: 0 },
      breath: { min: -1, max: 1, value: 0 }, mouthOpen: { min: 0, max: 1, value: 0 },
      bodyY: { min: -200, max: 200, value: 0 }, bodyX: { min: -100, max: 100, value: 0 }, bodyRoll: { min: -10, max: 10, value: 0 },
    },
    render: { pixelRatio: 1, maxFps: 60, padding: 120, maxTextureBytes: 268435456, loadTimeout: 8000, maskCutoff: 0.08,
      rim: { enabled: true, color: [0.2, 0.65, 1], width: 2, strength: 0.5 } },
    motion: { smoothing: 11, breathPeriod: 3.4, breathAmount: 1, floatPeriod: 6.2, floatAmount: 8,
      swayPeriod: 7.1, swayAmount: 0.6, gazeGap: [3, 7], gazeAmount: [0.22, 0.13], talkRoll: 0.05 },
    blink: { minGap: 2.4, maxGap: 5.5, duration: 0.19, doubleChance: 0.2, doubleDelay: 0.28, asymmetry: 0.018 },
    eyes: { travel: [30, 18], halfThreshold: 0.7, closedThreshold: 0.22, highlightPulse: 0.15, highlightSpeed: 2.5, browTravel: 30 },
    mouth: { halfLevel: 0.035, openLevel: 0.10, hysteresis: 0.7, gain: 5, minOpen: 0.45, transition: 0.055 },
    deformers: {
      face: { type: 'head', pivot: [1024, 1250], angle: [10, 8], parallax: [430, 300], compress: 0.1, curve: 0.2 },
      hair: { type: 'bend', param: 'roll', angle: 2, axis: 'y' },
      breath: { type: 'breath', center: [1024, 2320], radius: [650, 620], amount: [16, -24] },
    },
    physics: {},
    emotions: {
      neutral: { pose: {}, brow: 'neutral', mouthVariant: '', effects: [] },
      happy: { pose: { blush: 0.45 }, brow: 'happy', mouthVariant: 'smile', action: { duration: 1.2, jump: 45, cycles: 2 }, effects: [{ kind: 'star', x: 1700, y: 600, size: 100 }] },
      excited: { pose: { blush: 0.7, roll: 0.08 }, brow: 'excited', mouthVariant: 'smile', action: { duration: 2, jump: 80, cycles: 4 }, effects: [{ kind: 'star', x: 1600, y: 500, size: 120, count: 3 }] },
      surprised: { pose: { brow: -0.65 }, brow: 'surprised', action: { duration: 0.5, jump: 110, cycles: 1 }, effects: [{ kind: 'bubble', x: 1600, y: 600, size: 100 }] },
      sad: { pose: { pitch: 0.55, roll: -0.15 }, eyes: { left: 'half', right: 'half' }, brow: 'sad', effects: [{ kind: 'drop', x: 1550, y: 1050, size: 80 }] },
      angry: { pose: { brow: 0.45 }, brow: 'angry', mouthVariant: 'angry', action: { duration: 0.7, shake: 30, frequency: 42 }, effects: [{ kind: 'anger', x: 1590, y: 730, size: 120 }] },
    },
    behaviors: {
      enabled: true,
      look: { cooldown: 8, duration: 2, pose: { yaw: -0.75, gazeX: -0.9, roll: -0.1 }, nodChance: 0.35, nodAmount: 0.3 },
      gift: { cooldown: 3, duration: 2.5, emotion: 'happy', effects: [{ kind: 'heart', x: 1550, y: 600, size: 110, count: 3 }, { kind: 'star', x: 500, y: 700, size: 90 }] },
      worry: { threshold: 0.3, pose: { pitch: 0.15, brow: 0.25 }, brow: 'sad', effectGap: 10, effects: [{ kind: 'drop', x: 1510, y: 1000, size: 70 }] },
      think: { gap: [12, 24], duration: 3, pose: { roll: 0.35, gazeY: -0.7, gazeX: 0.15 } },
      gameOver: { duration: 2, pose: { pitch: 0.2, gazeX: 0, gazeY: 0 } },
    },
  };

  // 仿射矩阵使用全画布坐标；子组矩阵累乘，父组旋转会自然带动子组枢轴。
  function multiply(a, b) {
    return [a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1],
      a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
      a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]];
  }
  function transform(spec, p) {
    const v = { x: 0, y: 0, rotation: 0, scaleX: 1, scaleY: 1, ...spec.transform };
    for (const [k, b] of Object.entries(spec.bindings || {})) {
      if (own(v, k)) v[k] += (p[b.param] || 0) * (b.gain ?? 1) + (b.offset || 0);
    }
    const [px, py] = spec.pivot || [0, 0], angle = v.rotation * rad;
    const a = Math.cos(angle) * v.scaleX, b = Math.sin(angle) * v.scaleX;
    const c = -Math.sin(angle) * v.scaleY, d = Math.cos(angle) * v.scaleY;
    return [a, b, c, d, px + v.x - a * px - c * py, py + v.y - b * px - d * py];
  }

  R.rig = async function createRigRenderer(stage, cfg, util) {
    // 包 JSON 本身也有超时，不能让一次挂起的请求永远拖住音频初始化。
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), DEFAULTS.render.loadTimeout);
    let source;
    try { source = await util.fetchJson(cfg.pack, { signal: controller.signal }); }
    catch (err) { if (err.name === 'AbortError') throw new Error('Rig 配置加载超时（8秒），请检查包路径/本地服务。'); throw err; }
    finally { clearTimeout(timer); }
    const pack = util.merge(DEFAULTS, source);
    const query = new URLSearchParams(location.search), wire = query.has('rigdebug');
    const base = new URL(cfg.pack, location.href), c = pack.canvas, d = cfg.display;
    const assert = (ok, text) => { if (!ok) throw new Error(`Rig 包错误：${text}`); };
    assert(pack.version === 1 && c && [c.width, c.height, c.charHeight].every((n) => finite(n) && n > 0), 'version/canvas');
    assert([c.anchorX, c.anchorY, d.charHeight, d.anchorX, d.anchorY].every(finite) && d.charHeight > 0, '锚点/显示尺寸');
    assert(Array.isArray(pack.parts) && pack.parts.length > 0 && pack.parts.length <= 128, 'parts 数量 1..128');
    const groups = new Map(), parts = new Map(), textures = new Map(), imageSizes = new Map(), resources = [];
    const vector = (v, n) => Array.isArray(v) && v.length === n && v.every(finite);
    function validTransform(spec) {
      assert(!spec.pivot || vector(spec.pivot, 2), `${spec.id} pivot`);
      assert(Object.values(spec.transform || {}).every(finite), `${spec.id} transform`);
      for (const binding of Object.values(spec.bindings || {})) {
        assert(binding && own(pack.parameters, binding.param) && finite(binding.gain ?? 1) && finite(binding.offset ?? 0), `${spec.id} bindings`);
      }
    }
    for (const [id, param] of Object.entries(pack.parameters)) {
      assert(param && [param.min, param.max, param.value].every(finite) && param.min <= param.max, `参数 ${id}`);
    }
    for (const [id, def] of Object.entries(pack.deformers)) {
      assert(def && ['head', 'breath', 'bend', 'cheek'].includes(def.type), `变形器 ${id} type`);
      if (def.type === 'head') {
        def.angle = def.angle || [10, 8];
        assert(vector(def.pivot, 2) && vector(def.parallax, 2) && vector(def.angle, 2) && def.angle.every((v) => v >= 0 && v <= 30) && [def.compress, def.curve].every(finite), `变形器 ${id}`);
      }
      if (def.type === 'breath') assert(vector(def.center, 2) && vector(def.radius, 2) && def.radius.every((v) => v > 0) && vector(def.amount, 2), `呼吸变形器 ${id}`);
      if (def.type === 'cheek') assert(Array.isArray(def.centers) && def.centers.length === 2 && def.centers.every((v) => vector(v, 2)) && vector(def.radius, 2) && def.radius.every((v) => v > 0) && vector(def.amount, 2) && own(pack.parameters, def.param || 'cheekPuff'), `脸颊变形器 ${id}`);
      if (def.type === 'bend') assert(own(pack.parameters, def.param) && finite(def.angle), `弯曲变形器 ${id}`);
    }
    for (const [id, spec] of Object.entries(pack.physics)) {
      const def = pack.physics[id] = { segments: 3, stiffness: 65, damping: 9, mass: 1, maxAngle: 25, drive: {}, ...spec };
      assert([def.segments, def.stiffness, def.damping, def.mass, def.maxAngle].every(finite) && def.maxAngle > 0 && def.maxAngle <= 45, `物理链 ${id}`);
      assert(Object.entries(def.drive).every(([key, gain]) => own(pack.parameters, key) && finite(gain)), `物理链 ${id} drive`);
    }
    for (const g of pack.groups || []) { assert(g.id && !groups.has(g.id), '组 id 重复/缺失'); validTransform(g); groups.set(g.id, g); }
    const orderedGroups = [], visiting = new Set(), visited = new Set();
    function visit(g) {
      assert(!visiting.has(g.id), `组循环 ${g.id}`);
      if (visited.has(g.id)) return;
      visiting.add(g.id);
      if (g.parent) { assert(groups.has(g.parent), `组父级 ${g.parent}`); visit(groups.get(g.parent)); }
      visiting.delete(g.id); visited.add(g.id); orderedGroups.push(g);
    }
    groups.forEach(visit);
    for (const p of pack.parts) {
      assert(p.id && !parts.has(p.id), '部件 id 重复/缺失');
      assert(!p.parent || groups.has(p.parent), `${p.id} 父级`);
      assert(Array.isArray(p.rect) && p.rect.length === 4 && p.rect.every(finite) && p.rect[2] > 0 && p.rect[3] > 0, `${p.id} rect`);
      assert(Array.isArray(p.pivot) && p.pivot.length === 2 && p.pivot.every(finite), `${p.id} pivot`);
      assert((p.deformers || []).every((key) => own(pack.deformers, key)), `${p.id} 变形器`);
      assert(!p.physics || own(pack.physics, p.physics), `${p.id} 物理链`);
      assert(p.image || Object.keys(p.variants || {}).length, `${p.id} 缺少图片/差分`);
      if (p.weights && !Array.isArray(p.weights)) assert(['x', 'y'].includes(p.weights.axis) && [p.weights.from, p.weights.to, p.weights.power ?? 1].every(finite) && p.weights.from !== p.weights.to && (p.weights.power ?? 1) > 0, `${p.id} 权重区间`);
      validTransform(p);
      parts.set(p.id, { ...p });
    }
    for (const [name, emotion] of Object.entries(pack.emotions)) {
      for (const [id, alpha] of Object.entries(emotion.layerOpacity || {})) assert(parts.has(id) && finite(alpha) && alpha >= 0 && alpha <= 1, `${name} layerOpacity`);
      for (const [key, motion] of Object.entries(emotion.oscillations || {})) assert(own(pack.parameters, key) && finite(motion.amplitude) && finite(motion.period) && motion.period >= 0.1 && (!own(motion, 'phase') || finite(motion.phase)), `${name} oscillations`);
      assert(!own(emotion, 'effectInterval') || (finite(emotion.effectInterval) && emotion.effectInterval >= 0.15), `${name} effectInterval`);
    }
    parts.forEach((p) => assert(!p.mask || (parts.has(p.mask) && p.mask !== p.id), `${p.id} mask`));
    const pad = clamp(pack.render.padding, 0, 1024), width = c.width + pad * 2, height = c.height + pad * 2;
    const scale = d.charHeight / c.charHeight, ratio = clamp(pack.render.pixelRatio, 0.5, 2);
    const wrap = document.createElement('div'); wrap.className = 'mesh-rig';
    Object.assign(wrap.style, { width: `${width * scale}px`, height: `${height * scale}px`,
      left: `${d.anchorX - (c.anchorX + pad) * scale}px`, top: `${d.anchorY - (c.anchorY + pad) * scale}px`,
      transformOrigin: `${(c.anchorX + pad) * scale}px ${(c.anchorY + pad) * scale}px`, transform: d.flip ? 'scaleX(-1)' : '' });
    const canvas = document.createElement('canvas'), overlay = document.createElement('canvas');
    canvas.width = overlay.width = Math.max(1, Math.round(width * scale * ratio));
    canvas.height = overlay.height = Math.max(1, Math.round(height * scale * ratio));
    wrap.append(canvas, overlay);
    const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, stencil: true, depth: false });
    if (!gl) throw new Error('WebGL 不可用；请启用 OBS 浏览器硬件加速。音频播放不受影响。');
    assert(gl.getContextAttributes().stencil, 'GPU 不支持眼白 stencil 遮罩');
    const ctx = overlay.getContext('2d');
    let contextLost = false;
    canvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); contextLost = true; });
    canvas.addEventListener('webglcontextrestored', () => { contextLost = true; }); // 音频不中断，提示刷新重建
    function resource(kind, value) { resources.push([kind, value]); return value; }
    function shader(type, source) {
      const sh = gl.createShader(type); gl.shaderSource(sh, source); gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) { const log = gl.getShaderInfoLog(sh); gl.deleteShader(sh); throw new Error(`Rig shader: ${log}`); }
      return sh;
    }
    const VS = 'attribute vec2 aPos; attribute vec2 aUV; uniform vec2 uSize; uniform float uPad; varying vec2 vUV; void main(){vUV=aUV;gl_Position=vec4((aPos.x+uPad)/uSize.x*2.0-1.0,1.0-(aPos.y+uPad)/uSize.y*2.0,0,1);}';
    function program(vs, fs) {
      const pr = resource('Program', gl.createProgram()), a = shader(gl.VERTEX_SHADER, vs), b = shader(gl.FRAGMENT_SHADER, fs);
      gl.attachShader(pr, a); gl.attachShader(pr, b); gl.linkProgram(pr); gl.deleteShader(a); gl.deleteShader(b);
      if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) throw new Error(`Rig shader link: ${gl.getProgramInfoLog(pr)}`);
      const loc = { pr };
      for (const name of ['aPos', 'aUV']) loc[name] = gl.getAttribLocation(pr, name);
      for (const name of ['uSize', 'uPad', 'uTex', 'uOpacity', 'uCutoff', 'uStep', 'uColor', 'uStrength']) loc[name] = gl.getUniformLocation(pr, name);
      return loc;
    }
    let drawProgram, rimProgram, target, frameBuffer;
    let bytes = 0, triangles = 0;
    try {
      drawProgram = program(VS, 'precision mediump float; varying vec2 vUV; uniform sampler2D uTex; uniform float uOpacity; uniform float uCutoff; void main(){vec4 c=texture2D(uTex,vUV);if(c.a<uCutoff)discard;gl_FragColor=c*uOpacity;}');
      rimProgram = program('attribute vec2 aPos;attribute vec2 aUV;varying vec2 vUV;void main(){vUV=aUV;gl_Position=vec4(aPos,0,1);}',
        'precision mediump float; varying vec2 vUV; uniform sampler2D uTex; uniform vec2 uStep; uniform vec3 uColor; uniform float uStrength; void main(){vec4 c=texture2D(uTex,vUV);float a=0.0;for(int x=-1;x<=1;x++){for(int y=-1;y<=1;y++){a=max(a,texture2D(uTex,vUV+vec2(float(x),float(y))*uStep).a);}}float edge=max(0.0,a-c.a)*uStrength;gl_FragColor=c+vec4(uColor*edge,edge)*(1.0-c.a);}');
      const paths = new Set();
      parts.forEach((p) => { if (p.image) paths.add(p.image); Object.values(p.variants || {}).forEach((path) => paths.add(path)); });
      assert(paths.size > 0 && paths.size <= 1024, '图片数量 1..1024');
      const maximum = gl.getParameter(gl.MAX_TEXTURE_SIZE);
      for (const path of paths) assert(typeof path === 'string' && /^[\w./-]+$/.test(path) && !path.includes('..') && !path.startsWith('/'), `非法图片路径 ${path}`);
      // 分批加载限制解码峰值，超时/缺图直接显式失败；绝不等到说话时加载差分。
      const list = [...paths];
      async function load(path) {
        const img = new Image();
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => { img.src = ''; reject(new Error(`Rig 图片加载超时：${path}`)); }, clamp(pack.render.loadTimeout, 100, 30000));
          img.onload = () => { clearTimeout(timer); resolve(); };
          img.onerror = () => { clearTimeout(timer); reject(new Error(`Rig 图片加载失败：${path}`)); };
          img.src = new URL(path, base).href;
        });
        assert(img.width <= maximum && img.height <= maximum, `${path} 超过 GPU 最大纹理尺寸 ${maximum}`);
        bytes += img.width * img.height * 4;
        assert(bytes <= pack.render.maxTextureBytes, '纹理超出 maxTextureBytes 预算');
        const tex = resource('Texture', gl.createTexture());
        gl.bindTexture(gl.TEXTURE_2D, tex); gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img); textures.set(path, tex); imageSizes.set(path, [img.width, img.height]);
      }
      for (let i = 0; i < list.length; i += 6) {
        const loaded = await Promise.allSettled(list.slice(i, i + 6).map(load));
        const failed = loaded.find((r) => r.status === 'rejected'); if (failed) throw failed.reason;
      }
      for (const p of parts.values()) {
        for (const path of [p.image, ...Object.values(p.variants || {})].filter(Boolean)) {
          const size = imageSizes.get(path);
          assert(size && size[0] === p.rect[2] && size[1] === p.rect[3], `${p.id} 的 ${path} 尺寸必须等于 rect 宽高（所有差分对齐）`);
        }
        const [nx, ny] = p.mesh || [4, 4];
        assert([nx, ny].every((n) => Number.isInteger(n) && n >= 1 && n <= 64), `${p.id} mesh 1..64`);
        const count = (nx + 1) * (ny + 1), indices = [];
        p.vertices = new Float32Array(count * 4); p.rest = new Float32Array(count * 2); p.weight = new Float32Array(count);
        if (Array.isArray(p.weights)) assert(p.weights.length === count && p.weights.every((w) => finite(w) && w >= 0 && w <= 1), `${p.id} 权重数组`);
        for (let j = 0; j <= ny; j++) for (let i = 0; i <= nx; i++) {
          const n = j * (nx + 1) + i, x = p.rect[0] + p.rect[2] * i / nx, y = p.rect[1] + p.rect[3] * j / ny;
          p.rest[n * 2] = x; p.rest[n * 2 + 1] = y; p.vertices[n * 4 + 2] = i / nx; p.vertices[n * 4 + 3] = j / ny;
          const w = p.weights || { axis: 'y', from: p.rect[1], to: p.rect[1] + p.rect[3] };
          p.weight[n] = Array.isArray(w) ? w[n] : Math.pow(clamp(((w.axis === 'x' ? x : y) - w.from) / ((w.to - w.from) || 1)), w.power || 1);
          if (i < nx && j < ny) indices.push(n, n + 1, n + nx + 1, n + 1, n + nx + 2, n + nx + 1);
        }
        p.nx = nx; p.ny = ny; p.indexCount = indices.length; triangles += indices.length / 3;
        p.buffer = resource('Buffer', gl.createBuffer()); p.indexBuffer = resource('Buffer', gl.createBuffer());
        gl.bindBuffer(gl.ARRAY_BUFFER, p.buffer); gl.bufferData(gl.ARRAY_BUFFER, p.vertices, gl.DYNAMIC_DRAW);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.indexBuffer); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);
      }
      target = resource('Texture', gl.createTexture()); gl.bindTexture(gl.TEXTURE_2D, target);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, canvas.width, canvas.height, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      frameBuffer = resource('Framebuffer', gl.createFramebuffer()); gl.bindFramebuffer(gl.FRAMEBUFFER, frameBuffer);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, target, 0);
      const stencil = resource('Renderbuffer', gl.createRenderbuffer()); gl.bindRenderbuffer(gl.RENDERBUFFER, stencil);
      gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_STENCIL, canvas.width, canvas.height);
      gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_STENCIL_ATTACHMENT, gl.RENDERBUFFER, stencil);
      assert(gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE, 'GPU 离屏缓冲不完整');
      if (gl.getError() !== gl.NO_ERROR) throw new Error('Rig GPU 纹理/缓冲分配失败');
    } catch (err) { for (const [kind, value] of resources) gl[`delete${kind}`](value); throw err; }
    const quad = resource('Buffer', gl.createBuffer()); gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 0, 0, 1, -1, 1, 0, -1, 1, 0, 1, 1, 1, 1, 1]), gl.STATIC_DRAW);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA); gl.disable(gl.DEPTH_TEST); gl.clearColor(0, 0, 0, 0);
    stage.appendChild(wrap);
    if (d.credit && pack.credit) {
      const el = document.createElement('div'); el.className = 'credit'; el.textContent = pack.credit;
      // 仅 rig 包可选覆盖；未提供时沿用旧位置，不改变 video/layers 的署名布局。
      const style = pack.creditStyle || {};
      for (const [key, maximum] of [['right', 1920], ['bottom', 1080], ['fontSize', 32]]) {
        if (finite(style[key])) el.style[key] = `${clamp(style[key], key === 'fontSize' ? 8 : 0, maximum)}px`;
      }
      if (finite(style.opacity)) el.style.opacity = String(clamp(style.opacity));
      stage.appendChild(el);
    }

    const p = {}, velocity = {}, limits = pack.parameters;
    for (const [key, def] of Object.entries(limits)) p[key] = def.value;
    const chains = new Map();
    for (const [id, def] of Object.entries(pack.physics)) {
      const n = Math.round(clamp(def.segments || 3, 1, 8)); chains.set(id, { def, q: new Float32Array(n), v: new Float32Array(n) });
    }
    const st = { now: 0, last: null, emotion: 'neutral', since: 0, speaking: false, visemes: [], mouth: 'N', band: 0,
      blink: { left: -100, right: -100 }, nextBlink: 0, second: 0, nextGaze: 0, gaze: [0, 0],
      lookAt: -100, lastLook: -100, nod: false, thinkAt: -100, nextThink: 0, giftAt: -100, lastGift: -100,
      gameOverAt: -100, screen: null, playRunning: false, worry: false, debugWorry: null, nextSweat: 0,
      fx: [], nextEmotionFx: Infinity, fxPreset: null, frames: 0, fpsSince: 0, fps: 0, cost: 0, maxCost: 0, mouthMode: 'volume', currentTime: 0 };
    const drawList = [...parts.values()].sort((a, b) => (a.z || 0) - (b.z || 0));
    const eyeValue = (key) => ({ open: 1, half: 0.55, closed: 0 }[key] ?? 1);
    function spawnFx(list, owner = null) {
      for (const effect of list || []) for (let i = 0; i < Math.min(effect.count || 1, 8); i++) {
        if (st.fx.length >= 32) st.fx.shift();
        const spread = effect.spread || [130, 100];
        st.fx.push({ ...effect, owner, since: st.now + i * 0.12, x: effect.x + (i ? rand(-spread[0], spread[0]) : 0), y: effect.y + (i ? rand(-spread[1], spread[1]) : 0) });
      }
    }
    function preset() {
      return pack.emotions[st.now - st.giftAt < pack.behaviors.gift.duration ? pack.behaviors.gift.emotion : st.emotion] || pack.emotions.neutral;
    }
    function setEmotion(emotion) {
      st.emotion = own(pack.emotions, emotion) ? emotion : 'neutral'; st.since = st.now;
      st.fx = st.fx.filter((effect) => effect.owner !== 'emotion');
      st.fxPreset = preset(); st.nextEmotionFx = st.now + (st.fxPreset.effectInterval || Infinity);
      spawnFx(st.fxPreset.effects, 'emotion');
    }
    function blink(side) {
      if (!side || side === 'left') st.blink.left = st.now;
      if (!side || side === 'right') st.blink.right = st.now + pack.blink.asymmetry;
    }
    function look(force = false) {
      if (!force && st.now - st.lastLook < pack.behaviors.look.cooldown) return;
      st.lastLook = st.lookAt = st.now; st.nod = Math.random() < pack.behaviors.look.nodChance;
    }
    function gift(force = false) {
      if (!force && st.now - st.lastGift < pack.behaviors.gift.cooldown) return;
      st.lastGift = st.giftAt = st.now; spawnFx(pack.behaviors.gift.effects);
    }
    // 观察广播不修改消息，不取得播放权；history 不触发陈旧的弹幕/礼物动作。
    function onMessage(data) {
      if (!pack.behaviors.enabled) return;
      if (data.type === 'danmaku' && data.item) {
        look(); if (['gift', 'sc', 'guard'].includes(data.item.kind)) gift();
      } else if (data.type === 'status') {
        const game = data.game || {};
        st.worry = finite(game.hp) && finite(game.max_hp) && game.max_hp > 0 && game.hp / game.max_hp <= pack.behaviors.worry.threshold;
        st.playRunning = game.play_running === true;
        if (game.screen === 'GAME_OVER' && st.screen !== 'GAME_OVER') st.gameOverAt = st.now;
        st.screen = game.screen;
      } else if (data.type === 'idle') setEmotion(data.emotion || 'neutral');
    }
    function mouth(level, info) {
      let key = 'N';
      const talking = st.speaking && info.speaking !== false && info.paused !== true;
      st.currentTime = finite(info.audioTime) ? Math.max(0, info.audioTime) : 0;
      st.mouthMode = st.visemes.length ? 'visemes' : 'volume';
      if (talking && st.visemes.length) {
        let lo = 0, hi = st.visemes.length;
        while (lo < hi) { const mid = (lo + hi) >> 1; if (st.visemes[mid].t <= st.currentTime) lo = mid + 1; else hi = mid; }
        key = lo ? st.visemes[lo - 1].v : 'N';
      } else if (talking) {
        const m = pack.mouth;
        if (level >= m.openLevel) st.band = 2;
        else if (st.band === 2 && level >= m.openLevel * m.hysteresis) st.band = 2;
        else if (level >= m.halfLevel) st.band = 1;
        else if (level < m.halfLevel * m.hysteresis) st.band = 0;
        else st.band = Math.min(st.band, 1);
        key = ['N', 'half', 'A'][st.band];
      } else st.band = 0;
      st.mouth = key;
      return key === 'N' ? 0 : clamp(level * pack.mouth.gain, pack.mouth.minOpen, 1);
    }
    function update(t, dt, level, info) {
      const m = pack.motion, b = pack.blink, behavior = pack.behaviors, e = preset();
      if (e !== st.fxPreset) { st.fxPreset = e; st.nextEmotionFx = t + (e.effectInterval || Infinity); }
      if (e.effectInterval && t >= st.nextEmotionFx) { spawnFx(e.effects, 'emotion'); st.nextEmotionFx = t + e.effectInterval; }
      if (t >= st.nextBlink) { blink(); st.nextBlink = t + rand(b.minGap, b.maxGap); if (Math.random() < b.doubleChance) st.second = t + b.doubleDelay; }
      if (st.second && t >= st.second) { blink(); st.second = 0; }
      if (t >= st.nextGaze) { st.gaze = [rand(-m.gazeAmount[0], m.gazeAmount[0]), rand(-m.gazeAmount[1], m.gazeAmount[1])]; st.nextGaze = t + rand(...m.gazeGap); }
      if (behavior.enabled && st.playRunning && !st.speaking && t >= st.nextThink) { st.thinkAt = t; st.nextThink = t + rand(...behavior.think.gap); }
      const target = {};
      for (const [key, def] of Object.entries(limits)) target[key] = def.value;
      Object.assign(target, e.pose);
      target.gazeX += st.gaze[0]; target.gazeY += st.gaze[1];
      target.breath = Math.sin(t * Math.PI * 2 / m.breathPeriod) * m.breathAmount * (cfg.motion.breath ?? 1);
      target.bodyY += Math.sin(t * Math.PI * 2 / m.floatPeriod) * m.floatAmount;
      target.bodyRoll += Math.sin(t * Math.PI * 2 / m.swayPeriod) * m.swayAmount * (cfg.motion.sway ?? 1);
      if (st.speaking) target.roll += Math.sin(t * 8) * level * m.talkRoll * (cfg.motion.talkBounce ?? 1);
      function pose(action, since, flipGaze = false) {
        const u = (t - since) / action.duration;
        if (u < 0 || u >= 1) return;
        const mix = Math.sin(Math.PI * u);
        for (const [key, value] of Object.entries(action.pose || {})) target[key] += value * mix * (flipGaze && d.flip && ['yaw', 'gazeX', 'roll'].includes(key) ? -1 : 1);
      }
      pose(behavior.look, st.lookAt, true);
      if (st.nod && t - st.lookAt < behavior.look.duration) target.pitch += Math.sin((t - st.lookAt) / behavior.look.duration * Math.PI * 2) * behavior.look.nodAmount;
      if (!st.speaking) pose(behavior.think, st.thinkAt);
      pose(behavior.gameOver, st.gameOverAt);
      const worried = st.debugWorry ?? st.worry;
      if (worried) {
        for (const [key, value] of Object.entries(behavior.worry.pose || {})) target[key] += value;
        if (t >= st.nextSweat) { spawnFx(behavior.worry.effects); st.nextSweat = t + behavior.worry.effectGap; }
      }
      const a = e.action, since = t - (t - st.giftAt < behavior.gift.duration ? st.giftAt : st.since);
      if (a && since >= 0 && since < a.duration) {
        const fade = 1 - since / a.duration;
        target.bodyY -= Math.abs(Math.sin(since / a.duration * Math.PI * (a.cycles || 1))) * (a.jump || 0) * fade;
        target.bodyX += Math.sin(since * (a.frequency || 30)) * (a.shake || 0) * fade;
      }
      // 持续表情微动与入场弹跳分开；所有参数仍经原有时间平滑与限幅。
      for (const [key, motion] of Object.entries(e.oscillations || {})) {
        target[key] += Math.sin(Math.max(0, since) * Math.PI * 2 / motion.period + (motion.phase || 0)) * motion.amplitude * clamp(since / 0.2);
      }
      target.mouthOpen = mouth(level, info);
      for (const side of ['left', 'right']) {
        const u = (t - st.blink[side]) / b.duration;
        const openness = u >= 0 && u < 1 ? 1 - Math.sin(u * Math.PI) : 1;
        target[side === 'left' ? 'eyeLeft' : 'eyeRight'] = Math.min(target[side === 'left' ? 'eyeLeft' : 'eyeRight'], eyeValue(e.eyes && e.eyes[side])) * openness;
      }
      const factor = 1 - Math.exp(-m.smoothing * dt);
      for (const [key, def] of Object.entries(limits)) {
        const old = p[key], value = clamp(target[key], def.min, def.max);
        // 眨眼保持快闭合；其余参数按时间平滑，不依赖固定帧率。
        p[key] += (value - p[key]) * (key.startsWith('eye') ? 1 : factor);
        velocity[key] = (p[key] - old) / Math.max(dt, 0.001);
      }
      const steps = Math.max(1, Math.ceil(dt * 120)), h = dt / steps;
      for (const chain of chains.values()) {
        const def = chain.def;
        let drive = 0; for (const [key, gain] of Object.entries(def.drive || {})) drive -= (velocity[key] || 0) * gain;
        drive = clamp(drive, -def.maxAngle, def.maxAngle);
        for (let step = 0; step < steps; step++) for (let i = 0; i < chain.q.length; i++) {
          const aim = i ? chain.q[i - 1] : drive;
          const mass = clamp(def.mass, 0.1, 10), k = clamp(def.stiffness, 1, 200), damping = clamp(def.damping, 0.1, 40);
          // 隐式二阶步进：小质量/大阻尼配置也稳定，不让显式 Euler 的速度项爆炸。
          chain.v[i] = (chain.v[i] + k * (aim - chain.q[i]) * h / mass) / (1 + damping * h / mass + k * h * h / mass);
          const next = chain.q[i] + chain.v[i] * h;
          chain.q[i] = clamp(next, -def.maxAngle, def.maxAngle);
          if (next !== chain.q[i]) chain.v[i] = 0;
        }
      }
      for (const def of Object.values(pack.deformers)) if (def.type === 'head') {
        def.sinYaw = Math.sin(p.yaw * def.angle[0] * rad); def.cosYaw = Math.cos(p.yaw * def.angle[0] * rad);
        def.sinPitch = Math.sin(p.pitch * def.angle[1] * rad); def.cosPitch = Math.cos(p.pitch * def.angle[1] * rad);
      }
      for (const g of orderedGroups) g.matrix = multiply(g.parent ? groups.get(g.parent).matrix : IDENTITY, transform(g, p));
    }

    function imageFor(part) {
      const e = preset(); let key = '';
      const replacement = e.partVariants && e.partVariants[part.id];
      if (replacement && part.variants && part.variants[replacement]) return part.variants[replacement];
      if (['eyeWhite', 'eyelid', 'pupil', 'highlight'].includes(part.role)) {
        const open = p[part.side === 'right' ? 'eyeRight' : 'eyeLeft'];
        key = open <= pack.eyes.closedThreshold ? 'closed' : open < pack.eyes.halfThreshold ? 'half' : 'open';
        // 可选的表情眼型仍走同一双眼状态机；旧包无此字段时不受影响。
        const variantName = typeof e.eyeVariant === 'string' ? e.eyeVariant : e.eyeVariant && e.eyeVariant[part.side];
        const variant = variantName && `${variantName}.${key}`;
        if (variant && part.variants && part.variants[variant]) key = variant;
      } else if (part.role === 'brow') key = (st.debugWorry ?? st.worry) ? pack.behaviors.worry.brow : e.brow || st.emotion;
      else if (part.role === 'mouth') {
        key = st.mouth; const variant = e.mouthVariant && `${e.mouthVariant}.${key}`;
        if (variant && part.variants && part.variants[variant]) key = variant;
      }
      return (part.variants && (part.variants[key] || part.variants.neutral || part.variants.N || part.variants.open)) || part.image;
    }
    function mesh(part) {
      const matrix = multiply(part.parent ? groups.get(part.parent).matrix : IDENTITY, transform(part, p));
      part.matrix = matrix;
      const [px, py] = part.pivot;
      for (let n = 0; n < part.weight.length; n++) {
        let x = part.rest[n * 2], y = part.rest[n * 2 + 1]; const weight = part.weight[n];
        for (const id of part.deformers || []) {
          const def = pack.deformers[id];
          if (def.type === 'head') {
            const dx = x - def.pivot[0], dy = y - def.pivot[1], depth = part.depth || 0;
            // 按配置角度作正交投影，再叠加美术可调的体积压缩/曲率（非完整 3D 模型）。
            x += def.sinYaw * def.parallax[0] * depth + dx * (def.cosYaw - 1)
              - dx * Math.abs(def.sinYaw) * def.compress + def.sinYaw * dy * dy / c.height * def.curve;
            y += def.sinPitch * def.parallax[1] * depth + dy * (def.cosPitch - 1);
          } else if (def.type === 'breath') {
            const dx = (x - def.center[0]) / def.radius[0], dy = (y - def.center[1]) / def.radius[1];
            const w = Math.exp(-2 * (dx * dx + dy * dy));
            x += dx * def.amount[0] * w * p.breath; y += def.amount[1] * w * p.breath;
          } else if (def.type === 'cheek') {
            // 紧支撑局部位移：椭圆外严格为0，颌缘、眼睛和嘴不被整脸缩放牵动。
            const amount = p[def.param || 'cheekPuff'] || 0;
            for (let side = 0; side < def.centers.length; side++) {
              const center = def.centers[side], dx = (part.rest[n * 2] - center[0]) / def.radius[0], dy = (part.rest[n * 2 + 1] - center[1]) / def.radius[1];
              const w = Math.max(0, 1 - dx * dx - dy * dy) ** 2 * amount;
              x += (side ? 1 : -1) * def.amount[0] * w; y += def.amount[1] * w;
            }
          } else if (def.type === 'bend') {
            let angle = (p[def.param] || 0) * (def.angle || 0);
            const chain = chains.get(part.physics);
            if (chain) {
              const at = weight * (chain.q.length - 1), lo = Math.floor(at), hi = Math.min(lo + 1, chain.q.length - 1);
              angle += chain.q[lo] + (chain.q[hi] - chain.q[lo]) * (at - lo);
            }
            angle *= weight * rad; const dx = x - px, dy = y - py;
            x = px + dx * Math.cos(angle) - dy * Math.sin(angle); y = py + dx * Math.sin(angle) + dy * Math.cos(angle);
          }
        }
        if (part.role === 'pupil' || part.role === 'highlight') { x += p.gazeX * pack.eyes.travel[0]; y += p.gazeY * pack.eyes.travel[1]; }
        if (part.role === 'brow') y += (p.brow + (p[part.side === 'right' ? 'browRight' : 'browLeft'] || 0)) * pack.eyes.browTravel;
        if (part.role === 'mouth' && st.mouth !== 'N') y = py + (y - py) * Math.max(pack.mouth.minOpen, p.mouthOpen);
        part.vertices[n * 4] = matrix[0] * x + matrix[2] * y + matrix[4];
        part.vertices[n * 4 + 1] = matrix[1] * x + matrix[3] * y + matrix[5];
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, part.buffer); gl.bufferSubData(gl.ARRAY_BUFFER, 0, part.vertices);
      const path = imageFor(part);
      if (part.path !== path) { part.previous = part.path; part.path = path; part.changed = st.now; }
    }
    function attributes(pr, buffer) {
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.enableVertexAttribArray(pr.aPos); gl.vertexAttribPointer(pr.aPos, 2, gl.FLOAT, false, 16, 0);
      gl.enableVertexAttribArray(pr.aUV); gl.vertexAttribPointer(pr.aUV, 2, gl.FLOAT, false, 16, 8);
    }
    function partOpacity(part) {
      const map = preset().layerOpacity || {};
      return (part.opacity ?? 1) * (part.opacityParam ? p[part.opacityParam] : 1) * (map[part.id] ?? 1);
    }
    function draw(part, masking = false) {
      const pr = drawProgram;
      attributes(pr, part.buffer); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, part.indexBuffer);
      let opacity = masking ? 1 : partOpacity(part);
      if (!masking && part.role === 'highlight') opacity *= 1 - pack.eyes.highlightPulse * (0.5 + 0.5 * Math.sin(st.now * pack.eyes.highlightSpeed));
      gl.uniform1f(pr.uCutoff, masking ? pack.render.maskCutoff : 0.001);
      function layer(path, alpha) {
        if (!path || !textures.has(path) || alpha <= 0) return;
        gl.bindTexture(gl.TEXTURE_2D, textures.get(path)); gl.uniform1f(pr.uOpacity, clamp(alpha));
        gl.drawElements(gl.TRIANGLES, part.indexCount, gl.UNSIGNED_SHORT, 0);
      }
      if (!masking && part.role === 'mouth' && part.previous && pack.mouth.transition > 0) {
        const blend = clamp((st.now - part.changed) / pack.mouth.transition);
        layer(part.previous, opacity * (1 - blend)); layer(part.path, opacity * blend);
      } else layer(part.path, opacity);
    }
    function render() {
      const rim = pack.render.rim;
      gl.bindFramebuffer(gl.FRAMEBUFFER, rim.enabled ? frameBuffer : null);
      gl.viewport(0, 0, canvas.width, canvas.height); gl.stencilMask(255); gl.clear(gl.COLOR_BUFFER_BIT | gl.STENCIL_BUFFER_BIT);
      const pr = drawProgram; gl.useProgram(pr.pr); gl.uniform2f(pr.uSize, width, height); gl.uniform1f(pr.uPad, pad); gl.uniform1i(pr.uTex, 0);
      for (const part of drawList) mesh(part);
      for (const part of drawList) {
        if (partOpacity(part) <= 0) continue;
        if (part.mask) {
          gl.enable(gl.STENCIL_TEST); gl.stencilMask(255); gl.clear(gl.STENCIL_BUFFER_BIT);
          gl.stencilFunc(gl.ALWAYS, 1, 255); gl.stencilOp(gl.KEEP, gl.KEEP, gl.REPLACE); gl.colorMask(false, false, false, false);
          draw(parts.get(part.mask), true);
          gl.colorMask(true, true, true, true); gl.stencilMask(0); gl.stencilFunc(gl.EQUAL, 1, 255); gl.stencilOp(gl.KEEP, gl.KEEP, gl.KEEP);
        } else gl.disable(gl.STENCIL_TEST);
        draw(part);
      }
      gl.disable(gl.STENCIL_TEST); gl.stencilMask(255);
      if (rim.enabled) {
        gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.clear(gl.COLOR_BUFFER_BIT); gl.useProgram(rimProgram.pr); attributes(rimProgram, quad);
        gl.bindTexture(gl.TEXTURE_2D, target); gl.uniform1i(rimProgram.uTex, 0);
        gl.uniform2f(rimProgram.uStep, rim.width * ratio / canvas.width, rim.width * ratio / canvas.height);
        gl.uniform3fv(rimProgram.uColor, rim.color); gl.uniform1f(rimProgram.uStrength, clamp(rim.strength)); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      }
    }
    function effects() {
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, overlay.width, overlay.height);
      ctx.setTransform(overlay.width / width, 0, 0, overlay.height / height, pad * overlay.width / width, pad * overlay.height / height);
      st.fx = st.fx.filter((f) => st.now - f.since < (f.duration || 1.7));
      for (const f of st.fx) {
        const u = (st.now - f.since) / (f.duration || 1.7); if (u < 0) continue;
        let x = f.x, y = f.y - u * (f.rise ?? 170);
        if (f.parent && groups.has(f.parent)) {
          const def = pack.deformers.face;
          if (def && def.type === 'head' && f.parent === 'head') {
            const dx = x - def.pivot[0], dy = y - def.pivot[1], depth = f.depth ?? 0.6;
            x += def.sinYaw * def.parallax[0] * depth + dx * (def.cosYaw - 1) - dx * Math.abs(def.sinYaw) * def.compress + def.sinYaw * dy * dy / c.height * def.curve;
            y += def.sinPitch * def.parallax[1] * depth + dy * (def.cosPitch - 1);
          }
          const m = groups.get(f.parent).matrix, tx = m[0] * x + m[2] * y + m[4];
          y = m[1] * x + m[3] * y + m[5]; x = tx;
        }
        ctx.save(); ctx.translate(x, y); const size = f.size * Math.min(1, u * 8); ctx.scale(size, size);
        ctx.globalAlpha = Math.min(1, u * 8, (1 - u) * 3) * (f.opacity ?? 1); ctx.fillStyle = f.color || ({ star: '#ffe895', heart: '#ff93ba', drop: '#7bdfff', anger: '#ff707d', bubble: '#b8f6ff', question: '#b9e5ff', tear: '#8bdfff', blushLines: '#ed8194', steam: '#e4efff', orbit: '#ffe895' }[f.kind] || '#ffffff');
        ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = 0.075; ctx.beginPath();
        if (f.kind === 'heart') { ctx.moveTo(0, 0.35); ctx.bezierCurveTo(-0.9, -0.2, -0.35, -0.8, 0, -0.35); ctx.bezierCurveTo(0.35, -0.8, 0.9, -0.2, 0, 0.35); ctx.fill(); }
        else if (f.kind === 'drop' || f.kind === 'tear') { ctx.moveTo(0, -0.6); ctx.bezierCurveTo(-0.7, 0.3, -0.1, 0.65, 0.25, 0.2); ctx.quadraticCurveTo(0.4, 0, 0, -0.6); ctx.fill(); }
        else if (f.kind === 'question') { ctx.lineCap = 'round'; ctx.lineWidth = 0.105; ctx.moveTo(-0.28, -0.28); ctx.bezierCurveTo(-0.25, -0.69, 0.48, -0.66, 0.30, -0.17); ctx.quadraticCurveTo(0.04, 0.03, 0.03, 0.20); ctx.stroke(); ctx.beginPath(); ctx.arc(0.02, 0.43, 0.065, 0, Math.PI * 2); ctx.fill(); }
        else if (f.kind === 'blushLines') { ctx.lineCap = 'round'; ctx.lineWidth = 0.045; for (let i = -1; i <= 1; i++) { ctx.moveTo(i * 0.24 - 0.06, -0.2); ctx.lineTo(i * 0.24 + 0.06, 0.2); } ctx.stroke(); }
        else if (f.kind === 'steam') { ctx.lineCap = 'round'; ctx.lineWidth = 0.06; for (let i = -1; i <= 1; i++) { const x = i * 0.28, wobble = Math.sin(u * 8 + i) * 0.09; ctx.moveTo(x, 0.35); ctx.bezierCurveTo(x - 0.25 + wobble, 0.05, x + 0.23 + wobble, -0.1, x, -0.45); } ctx.stroke(); }
        else if (f.kind === 'orbit') { ctx.lineWidth = 0.02; ctx.globalAlpha *= 0.8; ctx.ellipse(0, 0, 1, 0.25, 0, 0, Math.PI * 2); ctx.stroke(); for (let i = 0; i < 5; i++) { const a = st.now * 2 + i * Math.PI * 2 / 5; ctx.save(); ctx.translate(Math.cos(a), Math.sin(a) * 0.25); ctx.rotate(a); ctx.beginPath(); for (let j = 0; j < 8; j++) { const angle = j * Math.PI / 4, r = j % 2 ? 0.05 : 0.14; ctx.lineTo(Math.sin(angle) * r, Math.cos(angle) * r); } ctx.closePath(); ctx.fill(); ctx.restore(); } }
        else if (f.kind === 'anger') { for (let i = 0; i < 4; i++) { ctx.rotate(Math.PI / 2); ctx.moveTo(0.12, -0.45); ctx.quadraticCurveTo(0.12, -0.12, 0.45, -0.12); } ctx.stroke(); }
        else if (f.kind === 'bubble') { ctx.arc(0, 0, 0.4, 0, Math.PI * 2); ctx.stroke(); ctx.beginPath(); ctx.arc(-0.15, -0.15, 0.08, 0, 7); ctx.fill(); }
        else { for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4, r = i % 2 ? 0.14 : 0.55; ctx.lineTo(Math.sin(a) * r, Math.cos(a) * r); } ctx.closePath(); ctx.fill(); }
        ctx.restore();
      }
      if (wire) {
        ctx.lineWidth = 1 / scale / ratio; ctx.strokeStyle = '#3cffe0'; ctx.globalAlpha = 0.55;
        for (const part of drawList) {
          ctx.beginPath();
          for (let j = 0; j <= part.ny; j++) for (let i = 0; i <= part.nx; i++) {
            const n = (j * (part.nx + 1) + i) * 4, v = part.vertices;
            if (i < part.nx) { ctx.moveTo(v[n], v[n + 1]); ctx.lineTo(v[n + 4], v[n + 5]); }
            if (j < part.ny) { const k = n + (part.nx + 1) * 4; ctx.moveTo(v[n], v[n + 1]); ctx.lineTo(v[k], v[k + 1]); }
          }
          ctx.stroke();
        }
        ctx.globalAlpha = 1; ctx.strokeStyle = '#ff548f';
        for (const spec of [...drawList, ...orderedGroups]) {
          const [x, y] = spec.pivot || [0, 0], m = spec.matrix, px = m[0] * x + m[2] * y + m[4], py = m[1] * x + m[3] * y + m[5];
          ctx.beginPath(); ctx.moveTo(px - 15, py); ctx.lineTo(px + 15, py); ctx.moveTo(px, py - 15); ctx.lineTo(px, py + 15); ctx.stroke();
        }
      }
    }
    return {
      kind: 'rig',
      start() {},
      speechStart(emotion, speech = {}) {
        st.speaking = true; st.band = 0;
        st.visemes = (Array.isArray(speech.visemes) ? speech.visemes : []).slice(0, 10000)
          .filter((v) => v && finite(v.t) && v.t >= 0 && ['N', 'A', 'I', 'U', 'E', 'O'].includes(v.v))
          .map((v) => ({ t: v.t, v: v.v })).sort((a, b) => a.t - b.t);
        setEmotion(emotion);
      },
      speechEnd() { st.speaking = false; st.visemes = []; st.band = 0; st.mouth = 'N'; },
      playEmotion: setEmotion, onMessage, blink,
      idleAction() { st.thinkAt = st.now; },
      debugAction(key, shift) {
        if (key === 'b') blink(shift ? 'left' : undefined);
        else if (key === 'l') look(true);
        else if (key === 't') st.thinkAt = st.now;
        else if (key === 'g') gift(true);
        else if (key === 'h') st.debugWorry = !(st.debugWorry ?? st.worry);
      },
      frame(t, level, info = {}) {
        if (contextLost) throw new Error('Rig WebGL 上下文丢失，请刷新形象源重建；音频仍继续播放。');
        // 高刷/无垂直同步的 headless 环境也不空耗 GPU；音频每帧采样和 ACK 不受限帧影响。
        if (st.last !== null && t - st.last < 1 / clamp(pack.render.maxFps, 15, 144) - 0.0005) return;
        const start = performance.now(), dt = st.last === null ? 1 / 60 : clamp(t - st.last, 0.001, 1 / 15);
        // 第一次 RAF 的时间可能很大，所有动作计时以同一单调时钟为准。
        if (st.last === null) { st.since = t; st.nextThink = t + rand(...pack.behaviors.think.gap); st.fpsSince = t; st.nextBlink = t + rand(pack.blink.minGap, pack.blink.maxGap); }
        st.now = t; st.last = t; update(t, dt, level, info); render(); effects();
        st.frames++; if (t - st.fpsSince >= 1) { st.fps = st.frames / (t - st.fpsSince); st.frames = 0; st.fpsSince = t; }
        const cost = performance.now() - start; st.cost += (cost - st.cost) * 0.1; st.maxCost = Math.max(st.maxCost, cost);
      },
      debugInfo() {
        return [`fps ${st.fps.toFixed(1)} | CPU帧 ${st.cost.toFixed(2)}ms / 峰值 ${st.maxCost.toFixed(2)}ms | ${triangles} 三角形 | 纹理 ${(bytes / 1048576).toFixed(1)} MiB`,
          `表情 ${st.emotion} / 嘴 ${st.mouth} (${st.mouthMode}) / 音频 ${st.currentTime.toFixed(2)}s / 低血量 ${st.debugWorry ?? st.worry}`,
          ...Object.keys(p).reduce((rows, key, i) => { const n = Math.floor(i / 4); rows[n] = (rows[n] || '') + `${key}=${p[key].toFixed(3)}  `; return rows; }, []),
          `物理 ${[...chains].map(([id, chain]) => `${id}=[${[...chain.q].map((v) => v.toFixed(1)).join(',')}]`).join(' ')}`].join('\n');
      },
    };
  };
})();
