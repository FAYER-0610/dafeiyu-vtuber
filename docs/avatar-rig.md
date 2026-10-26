# 小鲸鱼 2D 网格形象包 v1

这是自研 WebGL 1 渲染器，不是 Live2D Cubism 格式，无第三方运行库。`rig-test` 是脚本绘制的几何测试角色，**不是正式形象美术**。默认仍是 video。

## 1. 美术交付约定（先确认部件清单）

- 建议逻辑画布 **2048 × 3072**，原点左上，x 向右、y 向下；按约 2 倍源图设计，保留透明背景，不把背景/文字烘焙进去。这里所有坐标均为源图像素，不是 OBS 像素；不再额外乘 2。
- `canvas: {width:2048,height:3072,anchorX:1024,anchorY:3072,charHeight:2850}`。锚点为下缘中点，`charHeight` 是从实际最高可见点到下缘的美术高度。
- 显示比例 = `avatar.json.display.charHeight / canvas.charHeight`；推荐半身显示高度 330–480。显示锚点 `(1700,1080)`，下缘贴底。现有全局配置不自动更改。
- 每个部件导出透明 RGBA PNG，**裁切矩形为 `rect:[x,y,width,height]`**；同部件所有差分必须使用相同裁切范围、尺寸与对齐。边缘保留至少 8–16 源像素透明留白，避免网格和轮廓光截断。允许自包含 SVG 测试素材，不允许脚本、外链或字体依赖。
- 被遮住的脸、头皮、脖子、肩、发根需要补绘 40–100 源像素，不能只切可见碎片。允许继续拆分发束，使用同一父组并分别配置物理。
- 左右是**画面左右**（非角色解剖左右）。眼白必须是实心透明底形状，外轮廓之外 alpha=0；眼线/睫毛另置眼睑图层，普通眼不要把虹膜画在眼白里。星星眼等完整特殊眼可例外使用烘焙眼内图案，但必须隐藏普通虹膜/高光，见第9节。

|建议 id /部件|parent|建议 z|枢轴位置|网格列×行|depth|绑定|
|---|---|---:|---|---|---:|---|
|backHair 后发|head|0|后脑发根|10×16|-.4|hair|
|body 胸口/肩/衣服|body|10|腰部中点|12×14|0|breath|
|neck 脖子|body|20|脖根|4×6|0|breath|
|face 脸（不含五官）|head|30|下巴/颈部连接点|12×12|.25|face|
|blushL / blushR 腮红|head|40|各自中心|4×4|.55|face，opacityParam=blush|
|eyeWhiteL / eyeWhiteR 眼白|head|50|各自中心|6×4|.6|face，role=eyeWhite|
|irisL / irisR 虹膜/瞳孔|head|51|各自中心|4×4|.65|face，role=pupil，mask=相应眼白 id|
|highlightL / highlightR 高光|head|52|各自中心|2×2|.65|face，role=highlight，mask=相应眼白 id|
|lidL / lidR 上眼睑/睫毛|head|53|各自中心|6×4|.65|face，role=eyelid|
|browL / browR 眉毛|head|60|各自中心|4×2|.65|face，role=brow|
|mouth 嘴|head|61|嘴中心|6×4|.7|face，role=mouth|
|frontHair 前发|head|70|前额发根|10×10|.8|hair|
|sideHairL / sideHairR 侧发|head|71|太阳穴|6×14|.5|hair|
|ahoge 呆毛|head|72|呆毛根部|4×10|.4|hair|
|ornament 头饰|head|80|固定点|4×4|.8|hair|
|ribbonL / ribbonR 丝带|head|81|蝴蝶结结点|4×10|.7|hair|
|whaleClip 鲸鱼发卡|head|82|固定点|4×4|.9|hair|
|tassel 金边蓝宝石菱形挂饰+蓝色流苏（可选）|head|83|挂饰固定点|6×14|.8|hair，独立更软弹簧链|
|chestBow 黑色大蝴蝶结+蓝宝石胸针（可选）|body|31|胸针固定点|8×6|.2|breath，可叠加轻微 hair 弯曲|

流苏建议独立链 k=27,d=4、5节，比丝带更软、回弹更明显；胸前蝴蝶结建议 k=85,d=11、小幅度跟随呼吸。`rig-test` 已包含这两项。动漫“透发眉”允许把 brow 的 z 放在 frontHair 之上，并设置 opacity=.6–.75；全局 z 排序和任意部件透明度均受支持，测试包使用 z=75、opacity=.7。

以上部件均建议提供；身体可细拆衣领、左右肩、手臂，z 自由细分。`parent` 引用组，不直接引用图片部件。默认组链为 `root → body → head`，可以增加任意层次的组。组和图片枢轴均使用**全画布绝对坐标**；图片裁切不会改变枢轴含义。

## 2. 最小包结构

将 `avatar.json` 的 renderer 改为 `rig`、pack 改为包内 `rig.json` 即可切换；试用请使用 URL，不修改默认配置。

```json
{
  "version": 1,
  "canvas": {"width":2048,"height":3072,"anchorX":1024,"anchorY":3072,"charHeight":2850},
  "groups": [
    {"id":"root","pivot":[1024,3072],"bindings":{"y":{"param":"bodyY","gain":1}}},
    {"id":"body","parent":"root","pivot":[1024,2900],"bindings":{"rotation":{"param":"bodyRoll","gain":1}}},
    {"id":"head","parent":"body","pivot":[1024,1740],"bindings":{"rotation":{"param":"roll","gain":10},"y":{"param":"pitch","gain":32}}}
  ],
  "parts": [
    {"id":"face","parent":"head","image":"face.png","rect":[520,600,1008,1200],"z":30,"pivot":[1024,1740],"mesh":[12,12],"depth":0.25,"deformers":["face"]}
  ]
}
```

`rig-test/rig.json` 是完整可运行参考，比最小示例包括更多可调项。所有资源相对 rig.json；必须同源相对路径，禁止 `..`、绝对路径、协议 URL。启动时全部差分预载，缺图报错，不在播报期间网络切图。

### part 字段

- `id` 唯一；`parent` 组 id；`z` 跨所有组全局排序（不是 DOM 层叠）。
- `image` 默认图片；`variants` 为键→图片路径；`rect` 图片占据的源画布矩形；`pivot` 绝对枢轴。
- `mesh:[列数,行数]` 每维 1–64；推荐 2–16；总部件不超过 128。纹理尺寸需小于 GPU MAX_TEXTURE_SIZE，建议单图 ≤4096。
- `transform:{x,y,rotation,scaleX,scaleY}` 固定偏移（源像素）、角度（度）、缩放；默认 0/0/0/1/1。`bindings` 与组相同，将参数乘 gain 后加到变换值，支持 offset。
- `depth` 建议 -1..1；`deformers` 引用命名变形器；`weights` 为 `{axis:"y",from:发根y,to:发梢y,power:1.5}`，结果 clamp(0..1)，支持 x 轴、反向区间；也可为逐顶点 0..1 数组（行优先，长度 `(列+1)*(行+1)`）。网格密度改变时应重算数组。
- `physics` 引用弹簧链 id；`opacity` 0..1；`opacityParam` 可绑定 `blush` 等参数。
- `role` 可为 `eyeWhite/pupil/highlight/eyelid/brow/mouth`；眼睛类另给 `side:"left"|"right"`；`mask` 引用眼白部件 id，以它**当前差分的变形后 alpha**写 stencil，裁切瞳孔与高光。透明阈值由 `render.maskCutoff` 调整。

### 差分键（必须同尺寸）

- 眼白、眼睑：`open / half / closed`，左右独立部件。closed 眼白应全透明；closed 眼睑是闭眼线。可选表情预设 `eyeVariant:"happy"` 会先查找 `happy.open / happy.half / happy.closed`，缺失时仍回退普通开合键；例如正式包的笑眼使用独立上弯眼线和透明眼白，普通眨眼保持下弯闭合。
- 眉：`neutral / happy / excited / surprised / sad / angry`；缺失回退 neutral。
- 嘴：`N / A / I / U / E / O / half`。N 为闭嘴，half 用于无时间戳时的半张档；可附加 `smile.N`、`smile.A` 等、`angry.N` 等，按预设 mouthVariant 选取，缺失回退普通音素。N 的 smile 是微笑闭嘴；angry.N 是撇嘴。变体前缀是**通用字符串键，并非写死枚举**；可定义 `mouthVariant:"happy"` 与 `happy.N/happy.A/...`，happy 的开口差分可画露齿大笑。测试包覆盖 smile、happy（露齿）、angry 三组变体。
- 眼睛可用预设 `eyeLeft/eyeRight` 限制开合上限。眨眼独立叠加，不因表情半睁而失效。

## 3. 参数、变形器、物理

运动/行为/口型时间均为秒（唯一例外 `render.loadTimeout` 是毫秒）；`frame()` 的时间是单调时钟，口型使用独立 `info.audioTime`（HTMLAudioElement.currentTime）。角度用度，位置用源像素。

|参数|范围|意义|
|---|---|---|
|yaw / pitch / roll|-1..1|左右转头、点头（正值低头）、歪头；head 组 roll gain=10 对应 ±10°|
|gazeX / gazeY|-1..1|眼球左右/上下；正值朝画面右/下，翻转时行为自动补偿方向|
|eyeLeft / eyeRight|0..1|闭眼→半睁→全开|
|brow|-1..1|双眉公共偏移，负值上挑|
|browLeft / browRight|-1..1|左右眉额外偏移，默认0，不影响旧包|
|cheekPuff|0..1|局部双颊鼓起，默认0，需部件绑定cheek变形器|
|blush|0..1|腮红透明度|
|breath|-1..1|胸肩网格呼吸驱动，不是整图缩放|
|mouthOpen|0..1|音量驱动张口程度，只有开口差分纵向变化，N 不被压扁|
|bodyY / bodyX|源像素|浮动、跳跃、抖动|
|bodyRoll|度|身体轻微摇摆|

`parameters` 可逐项覆盖 `{min,max,value}`；所有目标经过 `motion.smoothing` 指数平滑。`motion` 控制呼吸周期/幅度、漂浮周期/幅度、摇摆周期/幅度、随机视线间隔与范围、说话摆幅。

`deformers` 为名称→配置，按部件列表顺序执行：

- `type:"head"`：`pivot`，`angle:[10,8]` 指定 yaw 最大 ±10°、pitch 最大 ±8°（每轴可调0–30°），先做 sin/cos 正交投影，再按 `depth * parallax:[430,300]` 给面部不同层加入投影视差；`compress:.1`、`curve:.2` 为美术额外体积压缩/弯曲。roll 则用 head 组 rotation 绑定（gain=10，即 ±10°）。这是轻量 2.5D，不是完整 3D 头部。
- `type:"breath"`：`center:[x,y]`、`radius:[x,y]`、`amount:[x,y]`。椭圆高斯权重让胸肩顶点局部扩张/上提，边界轻微或不动。
- `type:"cheek"`：`centers:[[左x,左y],[右x,右y]]`、`radius:[rx,ry]`、`amount:[水平,垂直]`、`param:"cheekPuff"`。以源坐标计算 `max(0,1-dx²-dy²)²` 紧支撑权重；左右分别向外平移，椭圆外位移严格为0。应把支撑域限制在面颊内部，避开眼睛/嘴/颌线，只给脸和腮红绑定；不是整体缩放脸轮廓。
- `type:"bend"`：`param`、`angle`（度）；按部件 weights（axis 默认建议 y）逐顶点绕 pivot 弯曲。有 physics 时额外采样链角度。

`physics` 是名称→配置：`segments` 1..8，`stiffness` 1..200（角加速度/角度），`damping` .1..40（速度阻尼），`mass` .1..10，`drive` 参数→速度耦合增益，`maxAngle` 1..45°。以 ≤1/120 秒子步进行隐式二阶积分（小质量/大阻尼也保持稳定），单帧 dt 最大 1/15 秒，避免后台恢复爆炸；各链节追随上一节，产生延迟与回弹。建议头发 k=65,d=9、丝带 k=40,d=7，发卡 k=110,d=12。权重 0 的发根固定，1 的发梢受全部弯曲。

## 4. 表情、眨眼、嘴型与行为配置

`emotions` 的表情键定义 `{pose:{参数:值},eyes:{left:"open",right:"half"},brow:"sad",mouthVariant:"smile",action:{duration,jump,cycles,shake,frequency},effects:[...]}`；动作单位是源像素。推荐开心小跳、兴奋多跳、惊讶单次弹起、难过 pitch 正、愤怒短时 shake。`effects` 每项 `{kind,x,y,size,duration,count,color}`，位置/尺寸为源像素；内置 canvas 绘制 `star/drop/anger/heart/bubble`，不下载图标。

- `blink:{minGap,maxGap,duration,doubleChance,doubleDelay,asymmetry}`：间隔、闭合再张开的总周期、双眨概率、两次起点间隔、左右起点偏差。
- `eyes:{travel:[x,y],halfThreshold,closedThreshold,highlightPulse,highlightSpeed,browTravel}` 控制眼球行程、差分门槛、高光透明微闪、眉位移。
- `mouth:{halfLevel,openLevel,hysteresis,gain,minOpen,transition}` 控制无时间戳三档滞回、张口幅度及差分交叉淡入秒数。
- 有有效 `speech.visemes:[{t:0,v:"N"},{t:.12,v:"A"},...]` 时优先按**实际音频时间**二分查找，时间戳无效项丢弃、排序并限制数量；不把接收消息时刻当音频开始。没有有效条目时才用 N/half/A 三档。音频 paused/ended 时闭嘴；表情嘴变体与音素组合。
- `behaviors.look`：`cooldown`（默认8秒）、`duration`、`pose`（通常 yaw/gazeX 为负）、`nodChance/nodAmount`。新弹幕只触发限频瞄左侧；history 不重放旧礼物。
- `behaviors.gift`：`cooldown/duration/emotion/effects`，kind=gift/sc/guard 触发开心、星星与爱心，不朗读内容。
- `behaviors.worry`：`threshold`（.3）、`pose`、`brow`、`effectGap/effects`；只在 hp/max_hp 均是有限数字且 max_hp>0 时判断。缺少状态立即清除推测。
- `behaviors.think`：`gap:[min,max]`、`duration/pose`；play_running===true 且没有说话时偶尔歪头上看。
- `behaviors.gameOver`：`duration/pose`。当前公开 status.game 不带胜负字段，所以 GAME_OVER 只触发中性停顿/点头，**不根据 hp 或 screen 猜胜负**；将来若明确公开结果，需要先更新协议与映射再做庆祝/失落。
- 根行为 `enabled:false` 关闭直播行为；`motion` 各幅度为 0 可关闭待机动作，blink 的 minGap/maxGap 可增大。

已核对 `host/web.py`：Hub.broadcast 发给所有 peers，**不按 viewer/avatar 分流**；初连各发 status/history，speech/emotion/idle 也广播。onMessage 可以观察全部包，但是否播放仍由 avatar.js 唯一播放器判断负责。渲染器接收冻结副本，不能修改协议状态，也不发送 WS、不操作游戏。

## 5. 渲染、错误与验证

`render:{pixelRatio:1,maxFps:60,padding:120,maxTextureBytes:268435456,loadTimeout:8000,maskCutoff:.08,rim:{enabled:true,color:[.2,.65,1],width:2,strength:.5}}`。pixelRatio 为显示画布倍率，建议 OBS=1；maxFps 限制高刷新率/无垂直同步环境的无效绘制，范围15–144、默认60，不限制音频和ACK；padding 为源像素安全边界。loadTimeout 是每张素材的毫秒超时，包JSON本身另有固定8秒启动超时。轮廓光对整个人物离屏合成的 alpha 做邻域 shader，避免给五官内边缘加光；width 为输出像素。显存预算含已解码纹理估算（RGBA 4字节），不含浏览器自身缓存；建议压缩 PNG、控制差分数。

WebGL 不可用、超时、缺图、包结构错误、运行/上下文丢失均显示清晰错误；音频/ready/ack 与渲染调用隔离。context 恢复后需刷新重建，不悄悄重播语音。

核心接口保持 `{kind,start(),speechStart(emotion,speech),speechEnd(),playEmotion(emotion),frame(t,level,info),debugInfo(),idleAction?,blink?,onMessage?}`；新增的 speech/info 参数对旧 video/layers 无副作用。`info` 为 `{audioTime,speaking,paused,speechId}`，仅实际 active 播放端的 speechStart 启动口型；所有广播（包括待机端收到的 speech）仍会交给只读 onMessage。`audioTime` 不随资源加载、缓冲或页面时钟漂移。

预览：`/overlay/avatar/?renderer=rig&pack=packs/rig-test/rig.json&offline&debug`；移除 offline 接入后端。加 `rigdebug` 显示变形后网格、组/部件枢轴；`debug` 显示 fps、CPU 帧耗时、参数、物理链角度。帧耗时不是 GPU 完成时间。

快捷键（debug 或 rigdebug）：1–6 原六表情；7=shy、8=smug、9=confused、0=cry、Q=pout、W=starry、E=dizzy、R=playful；I 空闲；Space 模拟说话；V 切换时间戳口型/音量口型；B 双眼眨、Shift+B 单左眼；L 看弹幕；T 思考；G 礼物；H 低血量切换。`?talk&visemes` 可模拟 N/A/I/U/E/O 序列。正式页面不暴露测试控制接口。

测试素材可用 `python3 -I scripts/make_rig_test.py` 重建；无 Pillow、无付费 API、无模型生图。建议对正式 PNG 切图另做对齐、补绘、遮罩、显存和 OBS CEF 实机验收。

## 8. 正式 `whale-maid` 包

- 路径：`overlay/avatar/packs/whale-maid/rig.json`；保留母版原生 **1024×1536**，不按前述新绘制素材的建议尺寸放大。29个真实分层部件，含左右长发束、双侧发、独立眼白/虹膜/高光/眼睑、透发眉、鲸鱼发卡、柔软流苏及胸前蝴蝶结。
- 重建：在项目外或可信工作目录执行 `python3 -I /绝对路径/vtuber-host/scripts/build_whale_maid.py`。依赖本地 Pillow、NumPy、OpenCV、SciPy；输入为同级 `avatar-original/master/final-03-ext.png` 和 `avatar-original/variants/*.png`。脚本不调用图像接口，不覆盖锁定母版，修复另存 `final-03-clean.png`。
- 21张正式差分（原12张+新增9张）共用原生裁切坐标；眼部差分剔除母版前发alpha，所有前发只取母版。A/O/U嘴型分别按嘴中心作0.75/0.85/1.30局部比例统一。缺失差分以母版占位，并在 `provenance.missingVariants` 明示；当前正式交付无缺失。
- 后脑、脸、脖子、肩部与配饰后方以本地肤色渐变/纹理延展补全；发片交界有22px发内渐隐搭接，根部物理较弱、梢部较软。不是把一张整图当底板伪装成分层。它仍是轻量2.5D角色，不适用于侧脸或大幅甩头。
- 显示建议（**未修改默认renderer/pack**）：`display:{charHeight:400,anchorX:1712,anchorY:1080,flip:false,credit:true}`。透明区不计入可见高度；母版名义可见高度1260。
- 预览：`/overlay/preview/?avatar&renderer=rig&pack=packs/whale-maid/rig.json&h=400&x=1712&y=1080`。单独调试可改为 `/overlay/avatar/?renderer=rig&pack=packs/whale-maid/rig.json&h=750&x=1150&y=1080&offline&debug`。
- 包内可选 `creditStyle:{right:430,bottom:4,fontSize:12,opacity:0.6}`，单位是1920×1080舞台像素，非源画布像素。只接受上述数值字段：right/bottom夹在舞台范围，字号8–32，opacity为0–1。正式包将署名放在字幕条下方空隙、右边缘x=1490；未提供此字段的rig包以及video/layers保留旧位置。大尺寸单独检视时，署名仍按直播舞台位置显示，不随人物缩放。
- 简短直播署名与完整许可分别见 `rig.json.credit` 和包内 `ATTRIBUTION.md`。角色CC BY-NC-SA 4.0，原型「溟月」作者B站上善无形、女仆鲸鱼娘设计B站ZipZipPipe，AI衍生母版，仅限非商业直播。

## 9. 14种表情与独立眼部覆盖

协议原六键 `neutral/happy/excited/surprised/sad/angry` 保留；新增八键如下。未知于某个rig包的情绪回退neutral；video找不到情绪片时维持当前播放，说话仍使用talk片；layers找不到情绪图时使用默认分层。无需替换旧包。

|键|预设|眼/嘴与动作|
|---|---|---|
|7|shy 害羞|波浪嘴、满腮红与红晕线、侧视/偏头、身体轻扭|
|8|smug 得意|半睁眼、猫嘴、微抬下巴、压眉、小闪光|
|9|confused 疑惑|思考嘴、左右眉分别偏移、歪头、问号|
|0|cry 哭哭|泪眼、哭嘴、下垂眉、眼角下落泪珠、抽泣微抖|
|Q|pout 鼓脸|嘟嘴、脸/腮红局部网格鼓起、蒸汽、短促弹跳|
|W|starry 星星眼|完整星星眼、隐藏原虹膜与高光、轻抬头前探、周围星光|
|E|dizzy 晕乎乎|完整旋涡眼、隐藏原虹膜与高光、波浪嘴、头部画圈、旋转星圈|
|R|playful 吐舌眨眼|画面左眼笑眼闭合、右眼睁开、吐舌、歪头、爱心|

向后兼容字段均为可选项，旧六情绪预设及旧包不需要迁移：

- `eyeVariant` 原字符串继续有效，也可给 `{left:"happy",right:"star"}`；未指定侧使用普通开合。`eyeWhite/eyelid/pupil/highlight` 都可提供 `前缀.open/.half/.closed` 差分。`eyes:{left:"closed",right:"open"}` 独立限制开合。
- `layerOpacity:{irisLeft:0,highlightLeft:0,...}` 按部件id乘透明度（0–1），为0时跳过该部件和其stencil写入。恢复普通表情自动还原；不改原图片、默认opacity或共享层。
- `partVariants:{irisLeft:"star"}` 可指定该部件 `variants.star` 作为当前表情图片，优先于自动眼/嘴差分；缺失安全回退原选择。需要随眨眼切换的虹膜替换优先使用 `eyeVariant` 的三态键。
- `oscillations:{roll:{amplitude:.25,period:2.1,phase:0}}` 给已有参数添加持续正弦微动；period单位秒（至少0.1），phase单位弧度，amplitude沿用该参数单位。入场0.2秒淡入，之后仍走统一平滑/限幅。它与一次性 `action` 分开，连续晕圈/抽泣不会在入场弹跳结束后停掉。
- `effectInterval` 为当前表情特效的重复间隔（秒，至少0.15）。不设则只在切表情时发射一次；切换表情清除上一表情所属粒子，不误清礼物/直播行为粒子。全局最多32个，单次count最多8个。
- 新特效 `question/tear/blushLines/steam/orbit` 全部由本地Canvas路径绘制，无字体图标/CDN。可选 `rise`（正值上漂，负值下落）、`opacity`、`spread:[随机x幅度,随机y幅度]`；默认rise=170。`parent:"head"` 会跟随head组和face头部变形，`depth` 默认0.6；其它parent跟随相应组矩阵。红晕线和旋转星圈使用rise=0，泪珠使用负rise。

正式包特殊眼沿母版开口取完整眼内图案，并剔除母版前发alpha；teary/star/dizzy都关闭旧虹膜/高光，防止重影。半闭合继续用正确stencil裁切，完全闭合用已验收低位闭眼弧线。半睁眼额外依据厚睫毛连通域下缘封住开口，避免上眼皮肤高光误写stencil而漏出旧虹膜碎片。

新增嘴差分只覆盖N（表情静止嘴）；说话仍切换A/I/U/E/O/half对应音素，不把整段讲话冻结为嘟嘴或吐舌。特殊眼是烘焙图案，因此这些表情下不再单独移动虹膜；头部转动、独立眨眼、口型和物理仍正常。

生成器为face采用18×18网格，局部鼓腮绑定脸与双腮红；颌缘支撑域外保持不动。当前正式包29部件、5176三角形，解码纹理约22.2MiB，新增9项源差分全部接入，无缺失。验证输出在项目同级 `.preview/whale-maid/`：`expression-<emotion>-750.png`、新增八种 `expression-<emotion>-400-composite.png`、14种汇总图与约8.34秒的 `fourteen-expressions.gif/.webm`。性能值来自Chrome JS侧，不代表OBS CEF/GPU实机耗时。
