# OBS WebSocket 协议 v1

端点 `ws://127.0.0.1:8765/ws`（端口随 config.yaml）；同源网页用 location.host 拼接。JSON UTF-8，无二进制帧。服务端消息共同字段 `type`, `v:1`, `ts`（Unix 秒）。所有文本必须用 textContent，禁止 innerHTML。

## 握手与唯一播放端

1. 连接后服务端发 `{"type":"hello","v":1,"client_id":"..."}`，随后 `status` 和最近安全弹幕的 `history`。
2. avatar 在可以播放时发送 `{"type":"hello","role":"avatar","ready":true}`；其他叠加页可发送 role=`viewer`。浏览器自动播放被拦时，请显示点击启用声音的按钮，启用后再 ready=true；OBS 浏览器源通常允许自动播放。
3. 服务端向每个 avatar 发 `{"type":"player","active":true|false,"client_id":"本连接ID"}`。同一时刻只有一个 active；其余是待机。只有 `speech.player_id === 本连接ID` 的 active avatar 可以播放音频。不要靠本地页面数猜测是否有别人播放。
4. 页面断开立刻停止自己的音频；后台页也必须响应取消。刷新后不会重播上一句。重新连接并重新 hello，指数退避 1–15 秒。`ready:false` 可释放播放器身份。

## 服务端 → 页面

### speech

```json
{"type":"speech","v":1,"ts":1790000000,"id":"uuid","text":"这场精英战可得小心啦！","emotion":"excited","audio_url":"/audio/uuid.mp3","duration_s":3.7,"timeout_s":15.7,"player_id":"active连接ID","visemes":[{"t":0.0,"v":"N"},{"t":0.1,"v":"E"},{"t":0.3,"v":"A"},{"t":3.6,"v":"N"}]}
```

- `emotion` 只允许以下14个精确小写值：`neutral / happy / excited / surprised / sad / angry / shy / smug / confused / cry / pout / starry / dizzy / playful`。原6种保持不变；缺失、大小写错误、未知值或非字符串均由主播大脑回落为neutral。
- `audio_url` 是同源相对地址；MP3（离线模式可为 WAV）。不带密钥。时长来自实际音频元数据；播放超时=时长+配置宽限。
- avatar 负责音频播放、WebAudio 分析/嘴型及表情；字幕页只显示，不播放。
- 推荐创建一个 AudioContext 和一个 audio 元素，用 createMediaElementSource → analyser → destination。用户点击后 resume；不可同时将同一音频接入两条 destination（重音）。
- 若新 id 到达，先停止旧音频。服务端本身串行，页面仍必须防御迟到消息。

#### 14种情绪的生成提示

| emotion | 适用场景（需话题事实支持） |
|---|---|
| neutral | 平静观察、等待或事实不足 |
| happy | 友好问候、小进展、温柔鼓励 |
| excited | 激烈战斗或已确认的重大进展 |
| surprised | 已确认的意外变化 |
| sad | 遗憾、受挫，温柔陪伴 |
| angry | 对险境轻微着急，不辱骂或责怪玩家 |
| shy | 被夸/收到礼物，害羞道谢，不引导消费 |
| smug | 有依据的好操作，或明确精英胜利 |
| confused | 奇怪事件、陌生怪物、资料不足 |
| cry | 明确大额掉血或失败，哭哭后温柔鼓励 |
| pout | 小失误、傲娇吐槽，不迁怒玩家 |
| starry | 明确稀有卡、心仪遗物，或确认赢下精英 |
| dizzy | 明确一次承受很多伤害，晕乎乎 |
| playful | 开玩笑、轻松卖萌、吐舌眨眼 |

这是模型系统提示的场景引导，不是新增的游戏事件→表情硬映射，也不是动作/胜负事实。GameTopics/Topic目前没有emotion_hint字段：hp/max_hp能证明当前残血，不能单凭它推断一次大量掉血；combat_ended不证明精英获胜；奖励阶段/卡名本身不证明稀有度。提示词禁止为了表情编造这些事实。只有game_over.is_victory明确本局胜负，其余须来自现有话题明确描述；证据不足使用neutral或confused。

形象页可以实现上述表情，但不应把表情名当成额外游戏事件。结束/取消仍按既有协议回neutral；speech/emotion字段名称、ACK和唯一player规则不变。

#### 可选 visemes 口型时间轴

`visemes` 是可选数组，旧页面忽略即可；缺失或空数组表示没有可用读音时间轴。每项严格为 `{t: number, v: "A"|"I"|"U"|"E"|"O"|"N"}`，t是相对**音频播放起点**的秒数、四舍五入到3位小数，按时间升序且同一毫秒最多一个状态。相邻相同口型合并，N表示闭口/静默。JSON数字不保留尾部零，0.1与0.100含义相同。上面speech示例的口型仅展示结构，不是该句的真实对齐。

前端应以 `audio.currentTime` 选择当前时间以前最后一项，不要按WS接收时刻或墙钟推进；从暂停恢复/seek时也使用当前播放时间。首次时间点前保持N；cancel、idle、断线和ended清空时间轴并闭口。唯一player与ACK规则完全不变。

来源与映射：
- ElevenLabs只调用 `/v1/text-to-speech/{voice_id}/with-timestamps`，保持 `eleven_flash_v2_5`、`language_code=zh`、`mp3_44100_128`；响应 `audio_base64` 解码后校验MP3与时长。接口失败按既有ProviderError处理，**不自动重试或回退到普通合成端点**。
- **合法原文alignment含中日韩文字时优先原文alignment**，中文按汉字转韵母，避免normalized_alignment将汉字罗马化为逐拉丁字母后高频切嘴。只有原文无效/不含CJK时才优先normalized_alignment，normalized无效则使用合法原文。官方OpenAPI只说明original/normalized text，不保证normalized一定保留汉字；本次真实探针原文12字符、normalized37字符，暴露了无条件优先normalized的问题。两者都无效/空时仍可播放有效音频，但visemes为空；不按真实台词均分伪造精确时间。
- 对齐数组是 `characters`、`character_start_times_seconds`、`character_end_times_seconds`。三个数组须等长、最多4096字符，数值有限非负、起点不倒序、终点不早于起点；最多容忍超出实际音频末尾0.25秒的编码/填充误差并裁剪。
- 本地pypinyin按整段文本取韵母以改善多音字；每字只选**一个主口型**，不拆复合韵母，不声称是声学音素级识别。

| 口型 | 韵母（不含声调） |
|---|---|
| A | a / ai / an / ang / ao / ia / iao / iang / ua / uai / uan / uang |
| I | i / ie / ian / in / ing / ü / üe / üan / ün，含v系列及ue别名 |
| U | u / ui / uei / un / uen / uo / ueng |
| E | e / ê / ei / en / eng / er |
| O | o / ou / ong / iong / iu / iou |

- 英文近似：a/e/i/o/u对应大写口型；b/m/p→N，w/q→U，y/j→I，其余ASCII字母→E。这不是英语词典音标对齐，也不尝试把没有CJK原文的拉丁序列猜成拼音音节。原文0～9按普通话单个数字近似（0→I、1→I、2→E、3→A、4→I、5→U、6→O、7→I、8→A、9→O）；例如28保留两处原文字时间点为E/A，不擅自插入“十”并虚构其时间。日文假名、韩文和其他未知字符闭口，不提供日/韩读音转换。
- 标点/空白→N；字符间隙大于0.12秒在上一字符结束时插入N；开头有空白保留N，最后补N并合并。0时长字符不打开嘴。
- 非N口型段短于60ms时并入相邻段：优先保持前一个非N口型；若前面是N/无前项，则把后一个非N口型前移并合并；两侧都是N的短开口被抑制。显式N停顿即使不足60ms也保留，不跨N填补元音。最终开放口型段至少60ms（按3位小数时间计算），防止逐字母高频抖动。
- 最多600项，超长时保留前段并在截断处闭口，后段不继续动画，避免一直张嘴；不会把最后一个元音拉长到整段结尾。
- offline模式是1秒测试提示音，按文本均分合成visemes，只供零收费前端联调，**不代表提示音有对应读音**。
- 依赖pypinyin==0.55.0，MIT许可证；见项目requirements和README。未安装中文映射依赖时在收费请求前报错。

### emotion / idle / speech_cancel

```json
{"type":"emotion","emotion":"happy","speech_id":"uuid"}
{"type":"speech_cancel","id":"uuid","reason":"timeout"}
{"type":"idle","last_speech_id":"uuid","reason":"ended","emotion":"neutral"}
```

cancel 必须 pause、清空 src、清理嘴型/字幕；idle 恢复空闲状态。reason 可能为 ended/error/timeout。服务端会校验 ACK 的连接身份、id 和结果。头像断线时不立刻切下一句，而等待当前音频时长+宽限后取消，避免网络抖动造成重叠；没有播放器时不调用收费模型/TTS。页面重新连接不会拿到在播 speech，待下一句。

### status / danmaku / history

`status` 包含 `layout.danmaku`（left/top/width/height，1920×1080 画布内像素，来自 config.yaml），以及字段 `banner`, `mode`（live/dry-run/offline）, `game_online`, `game_stream`, `bilibili`（disabled/connecting/connected/reconnecting）, `avatar_ready`, `speaking`, `game`（run_id, screen, floor, character, hp, max_hp, turn, teammate_online, play_running）, `stream`（live 是否在播、since 开播时间 ISO 字符串、diary 上一篇日记相对 memory/ 的路径、dynamic 动态结果说明）。不含任何配置密钥。

控制页 `/overlay/control/` 用 `POST /api/stream`，正文 `{"action": "start"|"end"}`，必须带同源 `Origin` 头，否则 403。`end` 立即返回，道别和下播整理在后台进行，结果通过 `status.stream` 推送。

`danmaku` 带 `item`: `{id, kind, uid, name, avatar, medal:{name,level}, time, text}`。kind 为 danmaku/gift/sc/enter/guard，time 为 Unix 秒。头像仅允许 HTTPS B站 CDN；缺失显示姓名首字。不安全内容不会推送。`history.items` 为最近至多 30 条。`danmaku_delete.ids` 为被平台删除的 SC 标识，页面应移除相同 id。

**avatar同样接收这些业务消息。** Hub.broadcast遍历全部连接，不按role过滤；danmaku、danmaku_delete、status、emotion、speech、speech_cancel、idle会发给avatar和viewer，未获播放权的avatar也能收到。history不是持续广播，而是在每个WS连接初始化时单独发送，随后avatar注册role不会失去该历史。player/ready_reset则按现有规则发给对应avatar。可以用安全弹幕、game.hp/max_hp、speaking等做非播音反应，但播放权限仍只由player_id决定；status没有LLM“正在思考”字段，不要把speaking=false理解为后端正在推理。

### ready_reset（ACK 超时恢复）

```json
{"type":"ready_reset","reason":"ack_timeout","retry_after_s":30,"manual_required":false}
```

连续第 1/2 次 ACK 超时，owner 失去 ready，分别在 30/60 秒后才可重新 `hello ready:true`。页面收到通知应停止音频；仅在 AudioContext 已 running 时按 `retry_after_s` 自动重注册。连续第 3 次发送 `retry_after_s:null, manual_required:true`，不再自动恢复，显示点击恢复按钮。用户点击后发送 `{type:"hello",role:"avatar",ready:true,recovery:"manual"}` 清零。正常 `speech_done status:ended` 清零计数。计数和冷却按当前 WS 连接；本机客户端属于信任边界。后端仍有每分钟/每小时费用上限。不要在 ready_reset 后额外发送 ready:false 造成恢复竞态。

## avatar → 服务端

```json
{"type":"speech_done","id":"uuid","status":"ended"}
{"type":"speech_done","id":"uuid","status":"error"}
{"type":"hello","role":"avatar","ready":false}
```

- 音频 ended 后才发 ended；播放失败/被 autoplay 拒绝发 error，并 ready=false，等待用户手动启用。
- 错误原因可在页面本地显示，服务端不接受任意文本日志。
- 不允许客户端注入 speech、弹幕、模型提示或修改游戏。未知消息忽略；帧大小限制 16KiB。

## 路由与安全边界

正式页面放 `overlay/avatar/index.html`，由 `/overlay/avatar` 提供；同目录资源可相对引用（路由会重定向到尾斜杠）。`/overlay/avatar-placeholder` 为测试播放器，正式直播请删除这个测试浏览器源，避免抢占唯一播放器。现有浏览器源用 `/overlay/danmaku`、`/overlay/subtitle`、`/overlay/status`。1920×1080 透明背景。

服务默认只监听 loopback，HTTP Host 与 WebSocket Origin 限定本机；无跨域开放。不要把端口转发到公网。无身份认证的原生本地 WS 客户端也能成为播放器，这是本机信任边界，不是公网服务。
