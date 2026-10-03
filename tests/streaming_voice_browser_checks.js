async page => {
  // Actual HTTP chunks, production guarded turn and native MP3 advancement.
  // Only local fictional adapters and the committed synthetic tone are used.
  const assert=require('node:assert/strict'), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const wait=async(label,predicate)=>{
    try { await page.waitForFunction(predicate,{},{timeout:15000}); }
    catch(error) {
      const media=await page.evaluate(()=>{
        const audio=document.getElementById('demo-audio');
        return {connected:state.connected,turnBusy:state.turnBusy,session:!!state.sessionId,
          currentTime:audio.currentTime,readyState:audio.readyState,ended:audio.ended,
          nativeError:audio.error?.code || null,playback:!!state.playback,
          complete:state.playback?.complete || false,interrupted:state.playback?.interrupted || false};
      });
      throw new Error(`${label}: ${error.name}; ${JSON.stringify(media)}`);
    }
  };
  await page.goto('http://127.0.0.1:8776/',{waitUntil:'networkidle'});
  await page.locator('#demo-language').selectOption('en');
  await page.locator('#token').fill('fixture-operator');
  await page.locator('#connect').click();
  await wait('actual catalog',()=>state.connected && state.voiceCatalog);
  assert.equal(await page.locator('#demo-voice option:enabled').count(),1,'actual catalog enabled unconfigured providers');
  assert.equal(await page.locator('#demo-voice').inputValue(),'azure');
  await page.locator('#demo-start').click();
  await wait('greeting completion',()=>state.sessionId && !state.turnBusy && document.getElementById('demo-audio').ended);
  await page.evaluate(()=>{
    window.syntheticTiming={sent:performance.now(),waiting:[]};
    document.getElementById('demo-audio').addEventListener('waiting',event=>{
      if(event.target.currentTime>0) window.syntheticTiming.waiting.push(event.target.currentTime);
    });
  });
   const requestedDay = await page.evaluate(()=>{
     const day=new Date(Date.now()+7*86400000);
     return new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Tallinn',year:'numeric',month:'2-digit',day:'2-digit'}).format(day);
   });
   await page.locator('#demo-text').fill(`Please reserve a table for four on ${requestedDay} at 18:00.`);
  await page.locator('#demo-send').click();
  await wait('first playback before provider completion',()=>state.turnBusy && document.getElementById('demo-audio').currentTime>.03);
  const early=await page.evaluate(async()=>({
    firstPlaybackMs:Math.round(performance.now()-window.syntheticTiming.sent),
    currentTime:document.getElementById('demo-audio').currentTime,
    awaitingReceipt:state.awaitingRecapId,
    ...(await fetch('/test/stream/state',{headers:{Authorization:'Bearer fixture-operator'}}).then(r=>r.json()))
  }));
  assert(early.started && !early.completed,'first playback waited for synthesis completion');
  assert.equal(early.awaitingReceipt,null,'partial output armed recap delivery');
  assert.equal(early.writes,0);assert.equal(early.records,0);
  await wait('native underrun',()=>window.syntheticTiming.waiting.length>0);
  await page.evaluate(()=>fetch('/test/stream/release',{method:'POST',headers:{Authorization:'Bearer fixture-operator'}}));
  await wait('resumed complete playback',()=>!state.turnBusy && document.getElementById('demo-audio').ended);
  const final=await page.evaluate(async()=>({
    automaticReceipt:state.recapDeliveryId,
    textReceipt:state.awaitingRecapId,
    waiting:window.syntheticTiming.waiting,
    ...(await fetch('/test/stream/state',{headers:{Authorization:'Bearer fixture-operator'}}).then(r=>r.json()))
  }));
  assert(final.completed && final.textReceipt,'successful canonical done lost explicit reading');
  assert.equal(final.automaticReceipt,null,'native underrun granted automatic acknowledgment');
  assert.equal(final.writes,0);assert.equal(final.records,0);
  assert(await page.locator('#demo-recap-read').isVisible());
  await page.locator('#demo-recap-read').click();
  assert(await page.evaluate(()=>state.recapDeliveryId===state.awaitingRecapId),'explicit text reading was lost');
  await page.locator('#demo-end').click();
  await wait('owned session cleanup',()=>!state.sessionId);
  await page.locator('#logout').click();
  assert.deepEqual(errors,[]);
  return {result:'passed',firstPlaybackBeforeSynthesisComplete:true,firstPlaybackMs:early.firstPlaybackMs,
    syntheticPlaybackPosition:early.currentTime,nativeUnderrunCount:final.waiting.length,
    underrunReceiptRejected:true,explicitTextAcknowledgment:true,fictionalWrites:final.writes,errors};
}
