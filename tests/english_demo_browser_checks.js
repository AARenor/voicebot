async page => {
  const assert = require('node:assert/strict');
  const requests=[], errors=[];
  page.on('pageerror', error=>errors.push(error.message));
  page.on('request', request=>{
    if (request.method()==='POST' && /\/api\/(turn|demo\/session)$/.test(new URL(request.url()).pathname)) requests.push({path:new URL(request.url()).pathname,body:request.postDataJSON()});
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
  await page.locator('#demo-language').selectOption('en');
  assert.equal(await page.locator('#demo-title').textContent(),'Try the voice assistant');
  assert.equal(await page.locator('#demo-section').getAttribute('lang'),'en');
  assert.equal(await page.locator('#demo-send').textContent(),'Send message');
  assert((await page.locator('#demo-models').textContent()).includes('en-US-JennyNeural'));
  assert((await page.locator('#demo-language-help').textContent()).includes('end this conversation'));
  await page.locator('#demo-start').click();
  assert((await page.locator('#demo-status').textContent()).includes('operator token'));
  assert.equal(requests.length,0,'signed-out language selection sent a private request');
  await page.locator('#token').fill('fixture-operator');await page.locator('#connect').click();
  await page.waitForFunction(()=>state.connected && !state.readBusy);
  const startResponse=page.waitForResponse(response=>response.url().endsWith('/api/demo/session'));
  await page.locator('#demo-start').click();
  const greeting=await (await startResponse).json();
  await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
  assert.equal(requests[0].body.language,'en');
  assert.equal(greeting.language,'en');
  assert(greeting.greeting.startsWith('Hi!'));
  assert(greeting.audio_b64 && !greeting.tts_failed);
  assert.equal(await page.locator('#demo-language').isDisabled(),true);
  assert.equal(await page.locator('#demo-messages strong').first().textContent(),'Demo assistant');
  await page.evaluate(()=>{document.getElementById('demo-language').value='et';changeDemoLanguage();});
  assert.equal(await page.locator('#demo-language').inputValue(),'en','active language changed without a fresh session');
  await page.locator('#demo-text').fill('Thank you');await page.locator('#demo-send').click();
  await page.waitForFunction(()=>!state.turnBusy);
  assert.equal(requests.at(-1).body.language,'en');
  assert.equal(await page.locator('#demo-messages .user-message strong').last().textContent(),'You');
  assert((await page.locator('#demo-messages .assistant-message').last().textContent()).includes("You're welcome"));
  await page.locator('[data-demo-example="hours"]').click();
  await page.waitForFunction(()=>!state.turnBusy);
  assert.equal(requests.at(-1).body.text,'What are the spa opening hours?');
  assert.equal(requests.at(-1).body.language,'en');
  // Synthetic Web Audio stream goes through real microphone capture/resampling.
  await page.evaluate(()=>{
    const context=new AudioContext(), sink=context.createMediaStreamDestination(), source=context.createOscillator(), gain=context.createGain();
    source.frequency.value=300;gain.gain.value=.08;source.connect(gain);gain.connect(sink);source.start();
    window.englishFixtureAudio={context,source};
    Object.defineProperty(navigator.mediaDevices,'getUserMedia',{configurable:true,value:async()=>sink.stream});
  });
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>state.mic && state.mic.frames>4096);
  assert.equal(await page.locator('#demo-mic').textContent(),'Stop and send audio');
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!state.micStarting && !state.turnBusy);
  assert(requests.at(-1).body.audio_b64,'microphone sent no audio');
  assert.equal(requests.at(-1).body.language,'en');
  await page.evaluate(async()=>{englishFixtureAudio.source.stop();await englishFixtureAudio.context.close();});
  // Autoplay failure and reading a recap never consent automatically.
  await page.route('**/api/turn',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({text_heard:'A test booking',language:'en',reply:'Test proposal. Say: Yes, I confirm.',outcome:'ok',recap_delivery_id:'b'.repeat(32),recap_expires_in_s:60,audio_b64:'',booking_changes:[],expires_in_s:590})}));
  await page.locator('#demo-text').fill('A test booking');await page.locator('#demo-send').click();
  await page.waitForFunction(()=>!state.turnBusy);
  assert(await page.locator('#demo-recap-read').isVisible());
  assert(await page.evaluate(()=>state.recapDeliveryId===null));
  await page.locator('#demo-recap-read').click();
  assert((await page.locator('#demo-status').textContent()).includes('Yes, I confirm.'));
  await page.locator('#demo-text').fill('Yes, I confirm.');await page.locator('#demo-send').click();
  await page.waitForFunction(()=>!state.turnBusy);
  assert.equal(requests.at(-1).body.recap_delivery_id,'b'.repeat(32));
  await page.unroute('**/api/turn');
  await page.locator('#demo-end').click();await page.waitForFunction(()=>!state.sessionId && !state.turnBusy);
  assert.equal(await page.locator('#demo-language').isDisabled(),false);
  await page.locator('#demo-language').selectOption('et');
  assert.equal(await page.locator('#demo-title').textContent(),'Proovi kõneabilist');
  assert.equal(await page.locator('[data-demo-example="hours"]').getAttribute('data-message'),'Millal spaa avatud on?');
  await page.locator('#demo-start').click();await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
  assert.equal(requests.at(-1).body.language,'et');
  assert((await page.locator('#demo-messages').textContent()).includes('Tere!'));
  await page.locator('#demo-end').click();await page.waitForFunction(()=>!state.sessionId && !state.turnBusy);
  await page.locator('#demo-language').selectOption('en');
  for (const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
    await page.setViewportSize({width,height});await page.locator('#demo-section').scrollIntoViewIfNeeded();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`${name} overflow`);
    const language=await page.locator('#demo-language').boundingBox();
    assert(language && language.height>=44 && language.width<=width,'language control is not usable');
    await page.screenshot({path:`output/playwright/english-demo-${name}.png`,fullPage:true});
    await page.locator('#demo-section').screenshot({path:`output/playwright/english-demo-panel-${name}.png`});
  }
  assert.deepEqual(errors,[]);
  return {result:'passed',sessionLanguages:requests.filter(request=>request.path.endsWith('/session')).map(request=>request.body.language),englishTurns:requests.filter(request=>request.path.endsWith('/turn') && request.body.language==='en').length,errors};
}
