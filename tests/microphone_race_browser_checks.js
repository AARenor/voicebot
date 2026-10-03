async (page) => {
  // A pending permission prompt must serialize every conversational input path.
  const assert=(ok,message)=>{if(!ok)throw new Error(message);};
  const requests=[],errors=[];
  const audio=Buffer.alloc(44+16000*10*2);
  audio.write('RIFF');audio.writeUInt32LE(audio.length-8,4);audio.write('WAVE',8);
  audio.write('fmt ',12);audio.writeUInt32LE(16,16);audio.writeUInt16LE(1,20);
  audio.writeUInt16LE(1,22);audio.writeUInt32LE(16000,24);audio.writeUInt32LE(32000,28);
  audio.writeUInt16LE(2,32);audio.writeUInt16LE(16,34);audio.write('data',36);
  audio.writeUInt32LE(audio.length-44,40);
  for(let i=0;i<160000;i++)audio.writeInt16LE(Math.sin(i*Math.PI/20)*4000,44+i*2);
  page.on('pageerror',()=>errors.push('page_error'));
  await page.route('**/api/**',route=>{
    const path=new URL(route.request().url()).pathname;
    if(route.request().method()==='DELETE')return route.fulfill({status:503,contentType:'application/json',body:'{}'});
    if(path==='/api/turn')requests.push(route.request().postDataJSON());
    const data=path==='/api/demo/session'?{session_id:'fixture',greeting:'Tere!',audio_b64:audio.toString('base64'),audio_type:'audio/wav'}:
      path==='/api/turn'?{reply:'Tere!',audio_b64:'',booking_changes:[]}:
      path==='/api/bookings'?{items:[],has_more:false}:
      path==='/api/calls'?{calls:[]}:
      path==='/api/call-history'?{items:[],summary:{},has_more:false}:{};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('http://127.0.0.1:8765/');
  await page.locator('#token').fill('fixture-operator');await page.locator('#connect').click();
  await page.waitForFunction(()=>state.connected && !state.readBusy);
  await page.locator('#demo-start').click();await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
  await page.evaluate(()=>{
    window.permissionPending=new Promise(resolve=>{window.permissionResolve=resolve;});
    Object.defineProperty(navigator.mediaDevices,'getUserMedia',{configurable:true,value:()=>permissionPending});
    window.openMicrophone=toggleMic();
  });
  await page.waitForFunction(()=>state.micStarting);
  const example=page.locator('.example-button').first();
  const disabled=await example.isDisabled();
  await page.evaluate(()=>sendTurn({text:'Millal spaa avatud on?'}));
  const serialized=requests.length===0;
  // Capture start retires the old audio URL. Restore local media while permission
  // is unresolved to prove the second guard still stops newly started playback.
  await page.locator('#demo-audio').evaluate(async (element,encoded)=>{
    const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
    window.raceAudioUrl=URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));
    element.src=raceAudioUrl;element.loop=true;element.currentTime=0;await element.play();
  },audio.toString('base64'));
  await page.waitForFunction(()=>!document.getElementById('demo-audio').paused && document.getElementById('demo-audio').currentTime>0.05);
  await page.evaluate(async()=>{
    window.raceContext=new AudioContext();await raceContext.resume();
    const sink=raceContext.createMediaStreamDestination();
    permissionResolve(sink.stream);await openMicrophone;
  });
  await page.waitForFunction(()=>!!state.mic);
  const paused=await page.locator('#demo-audio').evaluate(audio=>audio.paused);
  await page.evaluate(()=>stopMic());
  await page.evaluate(()=>{
    window.permissionPending=new Promise(resolve=>{window.permissionResolve=resolve;});
    window.openMicrophone=toggleMic();
  });
  await page.waitForFunction(()=>state.micStarting);
  await page.locator('#demo-end').click();await page.waitForFunction(()=>!state.turnBusy);
  assert(await page.evaluate(()=>!!state.sessionId),'failed-end control did not retain the server session');
  await page.evaluate(async()=>{
    const sink=raceContext.createMediaStreamDestination();window.cancelledStream=sink.stream;
    permissionResolve(sink.stream);await openMicrophone;
  });
  const cancelled=await page.evaluate(()=>!state.mic && cancelledStream.getTracks().every(track=>track.readyState==='ended'));
  await page.locator('#logout').click();await page.evaluate(()=>{URL.revokeObjectURL(raceAudioUrl);return raceContext.close();});
  assert(disabled,'example input remained enabled during microphone permission');
  assert(serialized,'pending microphone permission allowed another conversational turn');
  assert(paused,'microphone capture overlapped assistant playback');
  assert(cancelled,'failed session end revived cancelled microphone permission');
  assert(!errors.length,'uncaught browser error');
  return {result:'passed',serializedPermission:true,stoppedActivePlayback:true,failedEndCancelledPermission:true,errors};
}
