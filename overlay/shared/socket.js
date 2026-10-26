export function connect(onMessage, options={}) {
  let socket, retry=1000, timer, closed=false;
  const api={clientId:null,send(data){if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(data));},close(){closed=true;clearTimeout(timer);socket?.close();}};
  function open(){
    socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws`);
    socket.onopen=()=>{retry=1000;options.onConnection?.(true);};
    socket.onmessage=event=>{let data;try{data=JSON.parse(event.data);}catch{return;}if(data.type==='hello'){api.clientId=data.client_id;api.send({type:'hello',role:options.role||'viewer',ready:options.ready===true});}onMessage(data,api);};
    socket.onclose=()=>{api.clientId=null;options.onConnection?.(false);if(!closed){timer=setTimeout(open,retry);retry=Math.min(15000,retry*1.7);}};
    socket.onerror=()=>socket.close();
  }
  open();
  window.addEventListener('pagehide',()=>api.close());
  if(new URLSearchParams(location.search).has('preview'))document.body.classList.add('preview');
  return api;
}
