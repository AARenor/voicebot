async page => {
  const assert = require('node:assert/strict');
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/api/')) requests.push({path:new URL(request.url()).pathname,body:request.postDataJSON()});
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:8766/', {waitUntil:'networkidle'});
  assert(await page.locator('#demo-start').isDisabled());
  assert(await page.locator('#reservation-prepare').isDisabled());
  assert.equal(await page.locator('#menu-list li').count(),3);
  const languages = [
    {code:'en', greeting:'Hello!', menu:'What is on the menu?', soup:'Vegetable soup', confirmed:'confirmed', cancelled:'cancelled'},
    {code:'et', greeting:'Tere!', menu:'Milline on menüü?', soup:'Köögiviljasupp', confirmed:'kinnitatud', cancelled:'tühistatud'},
    {code:'ru', greeting:'Здравствуйте!', menu:'Что есть в меню?', soup:'Овощной суп', confirmed:'подтверждено', cancelled:'отменено'},
  ];
  await page.locator('#operator-token').fill('restaurant-fixture-operator');
  await page.locator('#connect').click();
  await page.waitForFunction(()=>state.connected && !state.readBusy);
  for (const language of languages) {
    await page.locator('#demo-language').selectOption(language.code);
    assert.equal(await page.locator('html').getAttribute('lang'),language.code);
    await page.locator('#demo-start').click();
    await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
    assert((await page.locator('#demo-messages').textContent()).includes(language.greeting));
    assert.equal(requests.at(-1).body.language,language.code);
    await page.locator('#demo-text').fill(language.menu);
    await page.locator('#demo-send').click();
    await page.waitForFunction(()=>!state.turnBusy);
    assert((await page.locator('#demo-messages').textContent()).includes(language.soup));
    assert(await page.locator('#demo-language').isDisabled());
    await page.locator('#demo-end').click();
    await page.waitForFunction(()=>!state.sessionId && !state.turnBusy);
    await page.locator('#reservation-time').fill('14:00');
    await page.locator('#reservation-party').fill('4');
    await page.locator('#reservation-prepare').click();
    await page.waitForFunction(()=>reservation.holdId && !reservation.busy);
    assert((await page.locator('#reservation-recap-text').textContent()).includes('4'));
    assert(await page.locator('#reservation-date').isDisabled(),'held recap allowed editable dates');
    assert(await page.locator('#demo-language').isDisabled(),'owned booking language changed');
    assert(await page.locator('#reservation-confirm').isDisabled(),'recap automatically granted consent');
    await page.locator('#reservation-read').click();
    await page.waitForFunction(()=>reservation.acknowledged && !reservation.busy);
    assert.equal(requests.at(-1).path,'/api/booking/recap');
    await page.locator('#reservation-confirm').click();
    await page.waitForFunction(()=>reservation.bookingId && !reservation.busy);
    assert((await page.locator('#bookings').textContent()).includes(language.confirmed));
    assert(await page.locator('#reservation-prepare').isDisabled(),'new preparation lost owned cancellation');
    await page.locator('#reservation-cancel').click();
    await page.waitForFunction(()=>!reservation.bookingId && !reservation.busy);
    assert((await page.locator('#bookings').textContent()).includes(language.cancelled));
    await page.locator('#reservation-end').click();
    await page.waitForFunction(()=>!reservation.sessionId && !reservation.busy);
    assert(!(await page.locator('#demo-language').isDisabled()));
  }
  // Real browser capture, filtering and 16k mono WAV encoding; recognition is a double.
  await page.locator('#demo-language').selectOption('en');
  await page.locator('#demo-start').click();
  await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
  assert(await page.locator('#demo-voice').isDisabled(),'voice selection changed an active conversation');
  await page.evaluate(()=>{window.restaurantOriginalPlay=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(){return Promise.reject(new Error('fixture autoplay denied'));};});
  const send = async text => {await page.locator('#demo-text').fill(text);await page.locator('#demo-send').click();await page.waitForFunction(()=>!state.turnBusy);};
  await send("I'd like to reserve a table");
  assert((await page.locator('#demo-messages .message').last().textContent()).includes('What date'));
  await send('tomorrow');
  assert((await page.locator('#demo-messages .message').last().textContent()).includes('What time'));
  await send('at 16:00');
  assert((await page.locator('#demo-messages .message').last().textContent()).includes('How many'));
  await send('for two adults and two children');
  assert(await page.locator('#demo-recap-read').isVisible());
  assert((await page.locator('#demo-messages .message').last().textContent()).includes('4 guests'));
  assert.equal(await page.evaluate(()=>state.recapDeliveryId),null,'failed autoplay authorized a booking');
  await page.locator('#demo-recap-read').click();
  const voiceReceipt=await page.evaluate(()=>state.recapDeliveryId);
  assert(voiceReceipt);
  await send('Yes, confirm.');
  const confirmedVoice=requests.findLast(request=>request.body.recap_delivery_id);
  assert.equal(confirmedVoice.body.recap_delivery_id,voiceReceipt);
  assert((await page.locator('#demo-messages .message').last().textContent()).includes('confirmed'));
  await send('Yes, cancel.');
  assert((await page.locator('#demo-messages .message').last().textContent()).includes('cancelled'));
  await page.evaluate(()=>{HTMLMediaElement.prototype.play=restaurantOriginalPlay;});
  await page.evaluate(()=>{
    const context=new AudioContext(),sink=context.createMediaStreamDestination(),source=context.createOscillator(),gain=context.createGain();
    source.frequency.value=300;gain.gain.value=.08;source.connect(gain);gain.connect(sink);source.start();
    window.restaurantAudio={context,source};
    Object.defineProperty(navigator.mediaDevices,'getUserMedia',{configurable:true,value:async()=>sink.stream});
  });
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>state.mic && state.mic.frames>4096);
  await page.locator('#demo-mic').click();
  await page.waitForFunction(()=>!state.micStarting && !state.turnBusy);
  const audioRequest=requests.findLast(request=>request.body.audio_b64);
  assert(audioRequest,'microphone sent no encoded audio');
  const wav=Buffer.from(audioRequest.body.audio_b64,'base64');
  assert.equal(wav.toString('ascii',0,4),'RIFF');assert.equal(wav.readUInt32LE(24),16000);assert.equal(wav.readUInt16LE(22),1);
  await page.evaluate(async()=>{restaurantAudio.source.stop();await restaurantAudio.context.close();});
  await page.locator('#demo-end').click();
  await page.waitForFunction(()=>!state.sessionId && !state.turnBusy);
  await page.screenshot({path:'output/playwright/restaurant-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile horizontal overflow');
  await page.screenshot({path:'output/playwright/restaurant-mobile.png',fullPage:true});
  // A late private reply must not restore data after disconnect.
  let release; const gate=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/bookings?**',async route=>{await gate;await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[],has_more:false})}).catch(()=>{});});
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>state.readBusy);
  await page.locator('#logout').click();release();
  await page.waitForFunction(()=>!state.connected && !state.readBusy);
  assert.equal(await page.locator('#bookings .booking-row').count(),0);
  assert.equal(await page.locator('#demo-messages .message').count(),0);
  assert(await page.locator('#reservation-confirm').isDisabled());
  assert.deepEqual(errors,[]);
  return {languages:3,confirmed:3,cancelled:3,voiceReservation:true,recapReceipt:true,microphoneWav:true,logoutIsolation:true,desktop:true,mobile:true,pageErrors:errors.length};
}
