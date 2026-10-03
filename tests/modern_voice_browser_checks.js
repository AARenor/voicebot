async page => {
  // Native MP3 decode/advancement, not a custom decoder or a fake played range.
  // Route fulfillment tests EOF/Blob/MSE acceptance, NOT time-to-first-byte.
  const assert=require('node:assert/strict'), fs=require('node:fs');
  const tone=fs.readFileSync('tests/fixtures/speech-tone.mp3').toString('base64');
  const requests=[], errors=[], paths=[];let mode='valid';
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/**',route=>{
    const request=route.request(), path=new URL(request.url()).pathname;
    paths.push(path);
    const json=data=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
    if(path==='/api/demo/voices')return json({endpointing_ms:650,voices:[
      {id:'azure',label:'Azure',languages:['et','en','ru'],configured:true,available:true,disabled_reason:null,streaming:true},
      {id:'elevenlabs',label:'ElevenLabs',languages:['et','en','ru'],configured:true,available:true,disabled_reason:null,streaming:true},
      {id:'google',label:'Google',languages:['et','en','ru'],configured:false,available:false,disabled_reason:'missing_credentials',streaming:false},
      {id:'cartesia',label:'Cartesia',languages:['en','ru'],configured:true,available:true,disabled_reason:null,streaming:true},
    ]});
    if(path==='/api/demo/session'){
      requests.push({path,body:request.postDataJSON()});return json({session_id:'modern-fixture',greeting:'Hi!',language:'en',audio_b64:''});
    }
    if(path==='/api/turn'){
      requests.push({path,body:request.postDataJSON(),accept:request.headers().accept});
      const reply={type:'reply',reply:'<img src=x onerror=bad> Guarded fictional recap.',language:'en',audio_type:'audio/mpeg'};
      const done={type:'done',reply:reply.reply,language:'en',text_heard:'Fictional request',audio_b64:'',audio_type:'audio/mpeg',outcome:'ok',booking_changes:[],recap_delivery_id:'a'.repeat(32),recap_expires_in_s:60,expires_in_s:590,voice:{requested:'elevenlabs',effective:'azure',language:'en',fallback:true,reason:'provider_unavailable',streaming:true}};
      const events=[reply,{type:'audio',seq:0,audio_b64:mode==='malformed'?'bm90LW1wMw==':tone}];
      if(mode!=='truncated')events.push(done);
      return route.fulfill({status:200,contentType:'application/x-ndjson',body:events.map(e=>JSON.stringify(e)+'\n').join('')});
    }
    return json({calls:[],items:[],services:[],providers:[],summary:{},has_more:false,fetched_at:'fixture'});
  });
  await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
  assert.equal(await page.locator('#demo-language').inputValue(),'auto');
  assert(await page.locator('#demo-voice').isDisabled());
  await page.locator('#demo-language').selectOption('en');
  await page.locator('#token').fill('fixture-operator');await page.locator('#connect').click();
  await page.waitForFunction(()=>state.connected && state.voiceCatalog);
  assert(await page.locator('#demo-voice option[value=google]').isDisabled());
  assert((await page.locator('#demo-voice-help').textContent()).includes('missing_credentials'));
  await page.locator('#demo-language').selectOption('et');
  assert(await page.locator('#demo-voice option[value=cartesia]').isDisabled(),'unsupported Estonian profile remained selectable');
  await page.locator('#demo-language').selectOption('en');
  assert(await page.locator('#demo-voice option[value=cartesia]').isEnabled(),'configured English profile was lost');
  const beforeVoiceChange=paths.length;
  await page.locator('#demo-voice').selectOption('elevenlabs');
  assert.equal(paths.length,beforeVoiceChange,'voice change sent a capability/authentication request');
  await page.locator('#demo-start').click();
  await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
  assert.equal(requests[0].body.voice,'elevenlabs');assert(await page.locator('#demo-voice').isDisabled());
  const send=async()=>{await page.locator('#demo-text').fill('Fictional request');await page.locator('#demo-send').click();await page.waitForFunction(()=>!state.turnBusy);};
  await send();
  assert.equal(requests.at(-1).accept,'application/x-ndjson');
  assert.equal(await page.locator('#demo-messages img').count(),0,'guarded reply injected HTML');
  assert((await page.locator('#demo-voice-result').textContent()).includes('Azure'),'effective fallback was hidden');
  await page.waitForFunction(()=>document.getElementById('demo-audio').currentTime>0.1);
  assert(await page.evaluate(()=>!state.recapDeliveryId),'partial playback acknowledged');
  await page.locator('#demo-audio').evaluate(a=>{a.currentTime=a.duration-.01;});
  await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
  assert(await page.evaluate(()=>!state.recapDeliveryId),'seek-to-end acknowledged');
  await send();await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
  assert(await page.evaluate(()=>state.recapDeliveryId==='a'.repeat(32)),'full native MP3 coverage did not acknowledge');
  await page.evaluate(()=>{document.getElementById('demo-voice').value='azure';changeDemoVoice();});
  assert.equal(await page.locator('#demo-voice').inputValue(),'elevenlabs','active voice changed without a fresh session');
  assert(await page.evaluate(()=>state.recapDeliveryId==='a'.repeat(32)),'rejected active voice change erased delivered consent eligibility');
  await page.evaluate(()=>{document.getElementById('demo-audio').play=()=>Promise.reject(new DOMException('fixture autoplay','NotAllowedError'));});
  await send();assert(await page.evaluate(()=>!state.recapDeliveryId));
  assert(await page.locator('#demo-audio').isVisible());assert(await page.locator('#demo-recap-read').isVisible());
  const beforeRead=requests.length;
  await page.locator('#demo-recap-read').click();assert(await page.evaluate(()=>!!state.recapDeliveryId));
  assert.equal(requests.length,beforeRead,'reading sent a turn or redundant acknowledgement');
  await page.evaluate(()=>{delete document.getElementById('demo-audio').play;});
  mode='truncated';await send();assert(await page.evaluate(()=>!state.recap && !state.recapDeliveryId));
  assert.equal(requests.at(-1).body.recap_delivery_id,'a'.repeat(32),'separate input lost the explicitly read receipt');
  mode='malformed';await send();await page.waitForFunction(()=>!state.audioUrl || document.getElementById('demo-audio').error);
  assert(await page.evaluate(()=>!state.audioUrl && state.playback?.failed && !state.recapDeliveryId),'decode failure acknowledged audio');
  assert(await page.locator('#demo-recap-read').isVisible(),'native decode failure discarded exact safe text reading');
  // Force feature detection fallback but leave native HTMLAudioElement untouched.
  await page.evaluate(()=>{window.MediaSource=undefined;});mode='valid';await send();
  await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
  assert(await page.evaluate(()=>state.recapDeliveryId==='a'.repeat(32)),'bounded Blob MP3 fallback failed');
  await page.locator('#logout').click();assert(await page.evaluate(()=>!state.audioUrl && !state.recapDeliveryId));
  assert.deepEqual(errors,[]);
  return {result:'passed',turns:requests.filter(r=>r.path==='/api/turn').length,nativeMp3:true,seekReceiptRejected:true,blobFallback:true,firstChunkTiming:'requires live local streaming fixture',errors};
}
