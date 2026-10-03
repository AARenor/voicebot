async (page) => {
  const failures = [], errors = [], requests = [];
  let replyReceipt = null, replyOutcome = 'ok';
  const assert = (ok, message) => { if (!ok) failures.push(message); };
  page.on('pageerror', error => errors.push(error.name));
  const audio = Buffer.alloc(44 + 16000 * 2 * 2);
  audio.write('RIFF'); audio.writeUInt32LE(audio.length - 8, 4); audio.write('WAVE', 8);
  audio.write('fmt ', 12); audio.writeUInt32LE(16, 16); audio.writeUInt16LE(1, 20);
  audio.writeUInt16LE(1, 22); audio.writeUInt32LE(16000, 24); audio.writeUInt32LE(32000, 28);
  audio.writeUInt16LE(2, 32); audio.writeUInt16LE(16, 34); audio.write('data', 36);
  audio.writeUInt32LE(audio.length - 44, 40);
  for (let i = 0; i < 32000; i++) audio.writeInt16LE(Math.sin(i * Math.PI / 20) * 4000, 44 + i * 2);
  const audio_b64 = audio.toString('base64');
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const reply = body => route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    if (path === '/api/turn') {
      requests.push(route.request().postDataJSON());
      return reply({text_heard:'Tere!',reply:'Tere! Kuidas saan aidata?',audio_b64,audio_type:'audio/wav',outcome:replyOutcome,recap_delivery_id:replyReceipt,expires_in_s:590,booking_changes:[]});
    }
    if (path === '/api/demo/session') return reply({session_id:'fixture-session',greeting:'Tere!',audio_b64,audio_type:'audio/wav',expires_in_s:600});
    if (path === '/api/calls') return reply({calls:[]});
    if (path === '/api/catalogue') return reply({services:[],providers:[]});
    if (path === '/api/bookings') return reply({items:[],fetched_at:'fixture',has_more:false});
    return reply({});
  });
  await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
  await page.locator('#token').fill('fixture-operator');
  await page.locator('#connect').click();
  await page.waitForFunction(()=>state.connected && !state.readBusy);
  await page.locator('#demo-start').click();
  await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
  assert(await page.locator('#demo-audio').evaluate(a=>!!a.src && !a.hidden),'start did not supply spoken greeting');
  await page.evaluate(()=>{document.getElementById('demo-audio').play=()=>Promise.reject(new DOMException('fixture autoplay','NotAllowedError'));});
  await page.locator('#demo-text').fill('Tere!');await page.locator('#demo-send').click();
  await page.waitForFunction(()=>!state.turnBusy);
  const rejected = await page.locator('#demo-status').textContent();
  assert(/Esita|esita/.test(rejected) && /heli|vastus/.test(rejected),'blocked playback was silently ignored');
  assert(await page.locator('#demo-audio').isVisible(),'blocked playback removed manual controls');
  await page.locator('#demo-audio').evaluate(a=>{delete a.play;a.dispatchEvent(new Event('error'));});
  assert(/heli|Heli/.test(await page.locator('#demo-status').textContent()),'media decode error was silent');
  assert(await page.evaluate(()=>!state.audioUrl && !state.recapDeliveryId),'decode error retained failed media or receipt');
  await page.evaluate(async data=>{
    const context = new AudioContext();await context.resume();
    const bytes = Uint8Array.from(atob(data), c=>c.charCodeAt(0));
    const buffer = await context.decodeAudioData(bytes.buffer);
    window.fixtureLoop=true;
    Object.defineProperty(navigator.mediaDevices,'getUserMedia',{configurable:true,value:async()=>{
      const sink = context.createMediaStreamDestination(), source = context.createBufferSource();
      source.buffer = buffer;source.loop = window.fixtureLoop;source.connect(sink);source.start();return sink.stream;
    }});
    window.fixtureContext=context;
    // Decode-error cleanup retired the previous source. Start a fresh valid
    // fixture before testing microphone interruption of advancing playback.
    playReply({audio_b64:data,audio_type:'audio/wav'});
    await document.getElementById('demo-audio').play();
  },audio_b64);
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!!state.mic);
  assert(await page.locator('#demo-audio').evaluate(a=>a.paused),'recorder captured assistant playback');
  await page.evaluate(()=>{state.mic.processor.onaudioprocess=()=>{};state.mic.chunks=[];state.mic.frames=0;});
  const before = requests.length;
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!state.mic && !state.turnBusy);
  assert(requests.length === before,'empty capture reached paid transcription');
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!!state.mic);
  await page.evaluate(()=>{
    state.mic.processor.onaudioprocess=()=>{};
    state.mic.chunks=[new Float32Array(4096)];state.mic.frames=4096;state.mic.peak=0;
  });
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!state.mic && !state.turnBusy);
  assert(requests.length===before,'silent nonempty capture reached paid transcription');
  const send = async text => {
    await page.locator('#demo-text').fill(text);await page.locator('#demo-send').click();
    await page.waitForFunction(()=>!state.turnBusy);
  };
  replyReceipt='a'.repeat(32);
  await page.locator('#demo-audio').evaluate(a=>{a.play=()=>Promise.reject(new DOMException('fixture autoplay','NotAllowedError'));});
  await send('Soovin testbroneeringut');
  assert(await page.evaluate(()=>state.recapDeliveryId===null),'blocked recap playback was acknowledged');
  assert(await page.locator('#demo-recap-read').isVisible(),'explicit reading acknowledgement missing');
  await page.locator('#demo-audio').evaluate(a=>{delete a.play;return a.play();});
  await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
  assert(await page.evaluate(()=>state.recapDeliveryId==='a'.repeat(32)),'completed recap was not acknowledged');
  replyReceipt=null;
  await send('Jah, kinnitan.');
  assert(requests.at(-1).recap_delivery_id==='a'.repeat(32),'completed-playback receipt not sent');
  replyReceipt='c'.repeat(32);
  await send('Kokkuvõte enne katkestust');
  await page.locator('#demo-audio').evaluate(a=>a.pause());
  assert(await page.evaluate(()=>!state.recapDeliveryId),'partial recap playback was acknowledged');
  replyReceipt=null;
  await send('Jah, kinnitan.');
  assert(!requests.at(-1).recap_delivery_id,'interrupted recap sent a consent receipt');
  replyReceipt='b'.repeat(32);
  await page.locator('#demo-audio').evaluate(a=>{a.play=()=>Promise.reject(new DOMException('fixture autoplay','NotAllowedError'));});
  await send('Teine testbroneering');
  await page.locator('#demo-recap-read').click();
  assert(await page.evaluate(()=>state.recapDeliveryId==='b'.repeat(32)),'explicit reading not acknowledged');
  replyReceipt=null; replyOutcome='unknown_outcome';
  await page.locator('#demo-audio').evaluate(a=>{delete a.play;});
  await send('Kontrolli tulemust');
  await page.waitForFunction(()=>document.getElementById('demo-audio').ended);
  assert((await page.locator('#demo-status').textContent()).includes('Ära korda'),'playback erased unknown-write warning');
  await page.locator('#demo-audio').evaluate(a=>a.dispatchEvent(new Event('error')));
  assert((await page.locator('#demo-status').textContent()).includes('Ära korda'),'audio error erased unknown-write warning');
  await page.evaluate(()=>{window.lateEnd=document.getElementById('demo-audio').onended;window.fixtureLoop=false;});
  const automatic = page.waitForResponse(r=>r.url().endsWith('/api/turn'),{timeout:6500});
  await page.locator('#demo-mic').click();
  try {await automatic;}
  catch (_) {
    failures.push('speech pause did not send automatically');
    if (await page.evaluate(()=>!!state.mic)) await page.locator('#demo-mic').click();
  }
  await page.waitForFunction(()=>!state.mic && !state.turnBusy);
  await page.locator('#demo-end').click();await page.waitForFunction(()=>!state.sessionId);
  await page.locator('#logout').click();await page.evaluate(()=>window.lateEnd?.());
  assert(await page.evaluate(()=>!state.mic && !state.audioUrl),'logout leaked media');
  assert(await page.evaluate(()=>!state.recapDeliveryId && !state.awaitingRecapId),'late event revived signed-out recap');
  await page.evaluate(()=>window.fixtureContext.close());
  assert(errors.length === 0,'uncaught browser error');
  if (failures.length) throw new Error(failures.join('; '));
  return {result:'passed',turns:requests.length,errors};
}
