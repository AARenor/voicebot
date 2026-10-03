async page => {
  const assert = require('node:assert/strict');
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().includes('/api/')) requests.push({path:new URL(request.url()).pathname,body:request.postDataJSON()});
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:8766/', {waitUntil:'networkidle'});
  const chooseLanguage = async code => page.locator('.language-option').filter({
    has: page.locator('input[value="' + code + '"]'),
  }).click();
  assert.equal(await page.getByRole('radio').count(), 3);
  assert(await page.getByRole('radio', {name:'Eesti', exact:true}).isChecked());
  for (const [code, name] of [['en','English'], ['ru','Русский'], ['et','Eesti']]) {
    assert(await page.getByRole('radio', {name, exact:true}).isVisible());
    assert(await page.getByRole('radio', {name, exact:true}).isEnabled());
    await chooseLanguage(code);
    assert.equal(await page.locator('html').getAttribute('lang'), code);
    assert.equal(await page.evaluate(()=>state.demoLanguage), code);
    assert.equal(await page.evaluate(()=>state.connected), false);
  }
  // Native radio keyboard navigation changes the same authoritative selection.
  await page.getByRole('radio', {name:'Eesti', exact:true}).focus();
  await page.keyboard.press('ArrowRight');
  assert(await page.getByRole('radio', {name:'English', exact:true}).isChecked());
  assert.equal(await page.locator('html').getAttribute('lang'), 'en');
  await page.keyboard.press('ArrowRight');
  assert(await page.getByRole('radio', {name:'Русский', exact:true}).isChecked());
  assert.equal(await page.locator('html').getAttribute('lang'), 'ru');
  await chooseLanguage('et');
  assert.equal(requests.length, 0, 'choosing a language called a provider before sign-in');
  assert.equal(await page.locator('aside.sidebar').count(),1,'restaurant adaptation removed the dashboard sidebar');
  assert.equal(await page.locator('.sidebar nav a').count(),4,'dashboard navigation is missing');
  for (const href of await page.locator('.sidebar nav a').evaluateAll(links=>links.map(link=>link.getAttribute('href')))) {
    assert(await page.locator(href).isVisible(),`navigation target ${href} is missing`);
  }
  const sidebarBox=await page.locator('.sidebar').boundingBox();
  const mainBox=await page.locator('main').boundingBox();
  assert(sidebarBox.x+sidebarBox.width<=mainBox.x,'desktop sidebar overlaps the workspace');
  assert.equal(await page.locator('.sidebar').evaluate(element=>getComputedStyle(element).position),'fixed');
  assert(await page.locator('.topbar').isVisible(),'dashboard topbar is missing');
  assert.deepEqual(await page.locator('a.demo-website-link').evaluateAll(links=>links.map(link=>link.href)),[
    'https://meretuule.arleserver.cfd/', 'https://meretuule.arleserver.cfd/'
  ]);
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
  await page.waitForFunction(()=>state.voiceCatalog);
  assert.equal(await page.locator('#demo-voice option:not(:disabled)').count(), 3);
  await chooseLanguage('et');
  for (const profile of ['azure-male', 'azure-calm']) {
    await page.locator('#demo-voice').selectOption(profile);
    await page.locator('#demo-voice-preview').click();
    await page.waitForFunction(()=>!state.previewBusy && !document.getElementById('demo-audio').hidden);
    assert.equal(requests.at(-1).path, '/api/demo/voices/preview');
    assert.equal(requests.at(-1).body.voice, profile);
    assert.equal(await page.evaluate(()=>state.sessionId), null, 'audition created a conversation');
    await page.waitForFunction(()=>document.getElementById('demo-audio').duration > 0);
    assert((await page.locator('#demo-voice-result').textContent()).includes(profile==='azure-male' ? 'Kert' : 'Anu'));
  }
  await page.screenshot({path:'output/playwright/natural-voices-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.locator('#demo-voice-preview').isVisible());
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:'output/playwright/natural-voices-mobile.png',fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await page.route('**/api/demo/voices/preview', route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'voice_preview_unavailable'})}));
  await page.locator('#demo-voice-preview').click();
  await page.waitForFunction(()=>!state.previewBusy);
  assert((await page.locator('#demo-status').textContent()).includes('Proovi uuesti'));
  assert.equal(await page.evaluate(()=>state.sessionId), null);
  await page.unroute('**/api/demo/voices/preview');
  await page.locator('#demo-voice').selectOption('azure');
  for (const language of languages) {
    await chooseLanguage(language.code);
    assert.equal(await page.locator('html').getAttribute('lang'),language.code);
    await page.locator('#demo-start').click();
    await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
    assert((await page.locator('#demo-messages').textContent()).includes(language.greeting));
    assert.equal(requests.at(-1).body.language,language.code);
    const hoursQuestions = {
      et: ['Mis kellani te lahti olete?', 'Aga nädalavahetusel?', 'Esmaspäevast neljapäevani'],
      en: ['What are your opening hours?', 'And on weekends?', 'Monday through Thursday'],
      ru: ['До скольки вы работаете?', 'А в выходные?', 'С понедельника по четверг'],
    }[language.code];
    for (const question of hoursQuestions.slice(0, 2)) {
      await page.locator('#demo-text').fill(question);
      await page.locator('#demo-send').click();
      await page.waitForFunction(()=>!state.turnBusy);
      const answer = await page.locator('#demo-messages .message').last().textContent();
      if (question === hoursQuestions[0]) assert(answer.includes(hoursQuestions[2]));
      else assert(answer.includes('23') && answer.includes('20') && !answer.includes('21'));
      assert.equal(await page.evaluate(()=>state.recap), null);
    }
    const petQuestions = {
      et: ['Tahaks tulla koeraga.', 'Kas kutsuga võib tulla?', 'Jah, koeraga võib tulla.'],
      en: ['Can I bring my dog?', 'Can we bring a puppy?', 'Yes, dogs are welcome.'],
      ru: ['Можно прийти с собакой?', 'Можно с питомцем?', 'Да, можно прийти с собакой.'],
    }[language.code];
    for (const question of petQuestions.slice(0, 2)) {
      await page.locator('#demo-text').fill(question);
      await page.locator('#demo-send').click();
      await page.waitForFunction(()=>!state.turnBusy);
      assert.equal(await page.locator('#demo-messages .message').last().locator('span').textContent(), petQuestions[2]);
      assert.equal(await page.evaluate(()=>state.recap), null);
    }
    await page.locator('#demo-text').fill(language.menu);
    await page.locator('#demo-send').click();
    await page.waitForFunction(()=>!state.turnBusy);
    assert((await page.locator('#demo-messages').textContent()).includes(language.soup));
    assert(await page.getByRole('radio', {name:'Eesti', exact:true}).isDisabled());
    await page.evaluate(code => {
      const input = document.querySelector('input[name="demo-language"][value="' + code + '"]');
      input.checked = true;
      input.dispatchEvent(new Event('change', {bubbles:true}));
    }, language.code === 'et' ? 'en' : 'et');
    assert.equal(await page.evaluate(()=>state.demoLanguage), language.code, 'active conversation language changed');
    assert.equal(await page.locator('input[name="demo-language"]:checked').inputValue(), language.code);
    assert(await page.locator('#demo-voice-preview').isDisabled(), 'audition interrupted an active conversation');
    await page.locator('#demo-end').click();
    await page.waitForFunction(()=>!state.sessionId && !state.turnBusy);
    await page.locator('#reservation-time').fill('14:00');
    await page.locator('#reservation-party').fill('4');
    await page.locator('#reservation-prepare').click();
    await page.waitForFunction(()=>reservation.holdId && !reservation.busy);
    assert((await page.locator('#reservation-recap-text').textContent()).includes('4'));
    assert(await page.locator('#reservation-date').isDisabled(),'held recap allowed editable dates');
    assert(await page.getByRole('radio', {name:'Eesti', exact:true}).isDisabled(),'owned booking language changed');
    assert(await page.locator('#reservation-confirm').isDisabled(),'recap automatically granted consent');
    await page.locator('#reservation-read').click();
    await page.waitForFunction(()=>reservation.acknowledged && !reservation.busy);
    assert.equal(requests.at(-1).path,'/api/booking/recap');
    // A previously selected later page must not hide a newly saved reservation.
    await page.evaluate(()=>{state.page=2;});
    await page.locator('#reservation-confirm').click();
    await page.waitForFunction(()=>reservation.bookingId && !reservation.busy);
    assert((await page.locator('#bookings').textContent()).includes(language.confirmed));
    assert.equal(await page.locator('#booking-page').textContent(),'1');
    assert.equal(await page.locator('#bookings .booking-recent').count(),1);
    assert(await page.locator('#reservation-status .booking-link').isVisible());
    assert(await page.locator('#reservation-prepare').isDisabled(),'new preparation lost owned cancellation');
    await page.locator('#reservation-cancel').click();
    await page.waitForFunction(()=>!reservation.bookingId && !reservation.busy);
    assert((await page.locator('#bookings').textContent()).includes(language.cancelled));
    await page.locator('#reservation-end').click();
    await page.waitForFunction(()=>!reservation.sessionId && !reservation.busy);
    assert(!(await page.getByRole('radio', {name:'Eesti', exact:true}).isDisabled()));
  }
  // Real browser capture, filtering and 16k mono WAV encoding; recognition is a double.
  await chooseLanguage('en');
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
  await page.evaluate(()=>{state.page=2;document.getElementById('booking-date').value=tallinnDay();});
  await send('Yes, confirm.');
  const confirmedVoice=requests.findLast(request=>request.body.recap_delivery_id);
  assert.equal(confirmedVoice.body.recap_delivery_id,voiceReceipt);
  assert((await page.locator('#demo-messages .message').last().textContent()).includes('confirmed'));
  const voiceBooking=await page.evaluate(()=>state.latestBooking);
  assert(voiceBooking && voiceBooking.date===await page.evaluate(()=>tallinnDay(1)));
  assert.equal(await page.locator('#booking-page').textContent(),'1');
  assert.equal(await page.locator('#bookings .booking-recent').getAttribute('data-booking-id'),voiceBooking.id);
  await page.locator('#demo-messages .booking-link').last().click();
  await page.waitForFunction(()=>document.activeElement?.dataset.bookingId===state.latestBooking.id);
  assert.equal(await page.locator('#booking-date').inputValue(),voiceBooking.date);
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
  // The Estonian ASR spelling uses the actual confirmation route and becomes
  // visible on the website. No external speech provider is used in this fixture.
  await chooseLanguage('et');
  await page.locator('#demo-start').click();
  await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
  await page.evaluate(()=>{HTMLMediaElement.prototype.play=function(){return Promise.reject(new Error('fixture autoplay denied'));};});
  await send('Soovin lauaks homseks kell 17.00 nelja inimesega');
  await page.locator('#demo-recap-read').click();
  await send('ja kinnitää');
  assert((await page.locator('#demo-messages .message').last().textContent()).includes('kinnitatud'));
  assert.equal(await page.evaluate(()=>state.latestBooking.date),await page.evaluate(()=>tallinnDay(1)));
  assert.equal(await page.locator('#bookings .booking-recent').count(),1);
  const estonianBooking=await page.evaluate(()=>state.latestBooking.id);
  await page.locator('#demo-end').click();
  await page.waitForFunction(()=>!state.sessionId && !state.turnBusy);
  await page.reload({waitUntil:'networkidle'});
  assert.equal(await page.locator('#bookings .booking-row').count(),0,'reload exposed private bookings without sign-in');
  await page.locator('#operator-token').fill('restaurant-fixture-operator');
  await page.locator('#connect').click();
  await page.waitForFunction(()=>state.connected && !state.readBusy);
  await page.locator('#booking-date').fill(await page.evaluate(()=>tallinnDay(1)));
  await page.locator('#booking-date').dispatchEvent('change');
  await page.waitForFunction(()=>!state.readBusy);
  assert((await page.locator(`#bookings [data-booking-id="${estonianBooking}"]`).textContent()).includes('kinnitatud'));
  await page.screenshot({path:'output/playwright/restaurant-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'mobile horizontal overflow');
  assert(await page.locator('.sidebar nav').isVisible(),'mobile dashboard navigation is missing');
  assert.equal(await page.locator('.sidebar').evaluate(element=>getComputedStyle(element).position),'static','mobile sidebar covers the controls');
  await page.locator('.sidebar nav a[href="#demo-section"]').click();
  assert.equal(new URL(page.url()).hash,'#demo-section');
  assert(await page.locator('#demo-start').isVisible(),'mobile navigation does not reach voice controls');
  await page.screenshot({path:'output/playwright/restaurant-mobile.png',fullPage:true});
  await page.setViewportSize({width:320,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'320px horizontal overflow');
  await page.setViewportSize({width:390,height:844});
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
  // Both hosts share one application; only the operator hostname gets the shell.
  await page.setViewportSize({width:801,height:844});
  await chooseLanguage('ru');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'801px Russian dashboard overflow');
  await page.setViewportSize({width:390,height:844});
  const fixtureOrigin=new URL(page.url()).origin;
  await page.route('https://meretuule.arleserver.cfd/**',async route=>{
    const url=new URL(route.request().url());
    const response=await route.fetch({url:fixtureOrigin+url.pathname+url.search});
    await route.fulfill({response});
  });
  await page.goto('https://meretuule.arleserver.cfd/',{waitUntil:'networkidle'});
  assert(await page.locator('.sidebar').isHidden(),'operator restoration changed the public restaurant demo');
  assert(await page.locator('.site-header > .brand').isVisible(),'public restaurant header was removed');
  assert.equal(await page.locator('html').evaluate(element=>getComputedStyle(element).backgroundColor),'rgb(245, 249, 246)','public restaurant palette changed');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'public mobile horizontal overflow');
  assert.deepEqual(errors,[]);
  return {languages:3,confirmed:3,cancelled:3,voiceReservation:true,estonianDateCaseForms:true,estonianAsrConfirmation:true,bookingVisibleAfterReload:true,bookingPageReset:true,recapReceipt:true,microphoneWav:true,logoutIsolation:true,desktop:true,mobile:true,publicDemoUnchanged:true,pageErrors:errors.length};
}
