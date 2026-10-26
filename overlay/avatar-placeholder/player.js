import {connect} from '/shared/socket.js';
const audio=document.querySelector('#audio'),text=document.querySelector('#text'),status=document.querySelector('#status'),button=document.querySelector('#enable');
let active=false,id=null,enabled=false,watchdog,retryTimer;
function stop(){clearTimeout(watchdog);audio.pause();audio.removeAttribute('src');audio.load();id=null;}
function done(result){if(id)ws.send({type:'speech_done',id,status:result});stop();}
async function enable(manual=false){try{const context=new AudioContext();await context.resume();await context.close();enabled=true;button.hidden=true;ws.send({type:'hello',role:'avatar',ready:true,...(manual?{recovery:'manual'}:{})});status.textContent='已启用，等待测试台词';}catch{button.hidden=false;}}
const ws=connect(async d=>{if(d.type==='hello'&&enabled)ws.send({type:'hello',role:'avatar',ready:true});
 if(d.type==='player'){active=d.active&&d.client_id===ws.clientId;status.textContent=active?'测试播放器已就绪':'待机；另一形象页可能正在播放';}
 if(d.type==='speech'&&active&&d.player_id===ws.clientId){stop();id=d.id;text.textContent=d.text;const url=new URL(d.audio_url,location.origin);if(url.origin!==location.origin){done('error');return;}audio.src=url.href;watchdog=setTimeout(()=>done('error'),(d.timeout_s+1)*1000);try{await audio.play();}catch{done('error');enabled=false;button.hidden=false;ws.send({type:'hello',role:'avatar',ready:false});}}
 if(d.type==='speech_cancel'&&d.id===id)stop();
 if(d.type==='idle'){text.textContent='';}
 if(d.type==='ready_reset'){stop();active=false;clearTimeout(retryTimer);if(d.manual_required){enabled=false;button.hidden=false;status.textContent='测试语音已暂停，请手动恢复';}else if(d.retry_after_s!==null){retryTimer=setTimeout(()=>{if(enabled)ws.send({type:'hello',role:'avatar',ready:true});},d.retry_after_s*1000);}}
},{role:'avatar',onConnection:online=>{if(!online){stop();active=false;status.textContent='连接断开，音频已停止';}}});
audio.addEventListener('ended',()=>done('ended'));
audio.addEventListener('error',()=>{if(id){done('error');enabled=false;button.hidden=false;ws.send({type:'hello',role:'avatar',ready:false});}});
button.addEventListener('click',()=>enable(true));
// OBS permits autoplay; browsers with an autoplay block require the visible button.
enable();
