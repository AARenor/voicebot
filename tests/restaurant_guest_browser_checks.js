// Real restaurant routes and public synthetic fixtures only; no live providers.
async (page) => {
  const assert=require('node:assert/strict');
  const errors=[],requests=[],posts=[],cases=[],failures=[],layouts=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{
    const url=new URL(request.url()); requests.push(url);
    if(request.method()==='POST')posts.push({path:url.pathname,body:request.postDataJSON()});
  });
  const check=async(name,action)=>{
    try { await action(); cases.push(name); }
    catch(error) { failures.push({name,message:error.message}); }
  };
  const fields=()=>page.locator('#booking-search-form input').evaluateAll(nodes=>Object.fromEntries(nodes.map(node=>[node.id,node.value])));
  const fill=async(date,time,party)=>{
    for(const [id,value] of [['new-table-date',date],['new-start-time',time],['new-party-size',party]]) {
      await page.locator('#'+id).fill(value);
      await page.locator('#'+id).dispatchEvent('change');
    }
  };
  const search=async()=>{
    const response=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/booking/search');
    await page.locator('#booking-search').click();
    const actual=await response;
    await page.waitForFunction(()=>!bookingUi.busy);
    return {status:actual.status(),body:await actual.json()};
  };
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:8765/?book=table',{waitUntil:'networkidle'});
  await page.locator('#token').fill('fixture-operator'); await page.locator('#connect').click();
  await page.waitForFunction(()=>state.connected && bookingUi.tables.length===5 && !state.readBusy);
  // Other booking checks retain short-lived holds on tomorrow's fixture date.
  const date=await page.evaluate(()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Tallinn'}).format(new Date(Date.now()+8*86400000)));
  const past=await page.evaluate(()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Tallinn'}).format(new Date(Date.now()-86400000)));
  await page.evaluate(()=>{
    window.fixtureFormSubmissions=0;
    document.getElementById('booking-search-form').addEventListener('submit',()=>fixtureFormSubmissions++);
  });
  // Removing field-specific feedback, focus, or the submit handler fails these.
  for(const input of [
    {name:'missing date before time and party',date:'',time:'',party:'',focus:'new-table-date',words:/kuupäev/i,other:/kellaaeg|inimeste arv/i},
    {name:'past date',date:past,time:'18:00',party:'4',focus:'new-table-date',words:/kuupäev/i,other:/kellaaeg|inimeste arv/i},
    {name:'missing time before party',date,time:'',party:'',focus:'new-start-time',words:/kellaaeg/i,other:/kuupäev|inimeste arv/i},
    {name:'invalid time precision',date,time:'18:00:30',party:'4',focus:'new-start-time',words:/kellaaeg/i,other:/kuupäev|inimeste arv/i},
    ...['','0','7','2.5'].map(party=>({name:'invalid party '+(party || 'missing'),date,time:'18:00',party,focus:'new-party-size',words:/1–6/,other:/kuupäev|kellaaeg/i})),
  ]) {
    await fill(input.date,input.time,input.party);
    const before=await fields(),sent=posts.length,submits=await page.evaluate(()=>fixtureFormSubmissions);
    await page.locator('#booking-search').click();
    await check(input.name,async()=>{
      const feedback=await page.locator('#new-booking-status').textContent();
      assert.match(feedback,input.words,'feedback did not identify the actual invalid field');
      assert.doesNotMatch(feedback,input.other,'feedback still lists unrelated fields');
      assert.equal(await page.locator('#'+input.focus).evaluate(node=>node===document.activeElement),true,'invalid field did not receive focus');
      assert.equal(await page.locator('#new-booking-status').evaluate(node=>node.classList.contains('error')),true);
      assert.equal(await page.evaluate(()=>fixtureFormSubmissions),submits+1,'native validation bypassed the real submit handler');
      if(input.focus==='new-party-size')assert.match(feedback,/lapsed/i,'party guidance excluded children');
      else assert.match(feedback,/Tallinna/i,'date/time guidance lost the Tallinn timezone');
      assert.deepEqual(await fields(),before,'validation silently changed another field');
      assert.equal(posts.length,sent,'invalid form sent a session, availability, or write request');
      assert.equal(await page.locator('.offer-button').count(),0);
      assert.equal(await page.locator('#booking-confirm').isDisabled(),true);
    });
  }
  await fill(date,'18:00','1');
  await check('one diner searches without selecting an offer',async()=>{
    const sent=posts.length;
    const result=await search();
    assert.equal(result.status,200); assert(result.body.offers.length>0);
    const request=posts.filter(post=>post.path==='/api/booking/search').at(-1).body;
    assert.equal(request.date,date); assert.equal(request.start_time,'18:00'); assert.equal(request.party_size,1);
    assert.equal(posts.slice(sent).filter(post=>post.path==='/api/booking/search').length,1);
    assert.equal(posts.slice(sent).filter(post=>!/\/(session|search)$/.test(post.path)).length,0,'search automatically prepared or confirmed an offer');
    assert.equal(await page.locator('#booking-recap').isHidden(),true);
  });
  // Occupy the only six-seat table with a real, disposable fixture hold.
  const headers={'Authorization':'Bearer fixture-operator','Content-Type':'application/json'};
  const fixture=await page.request.post('http://127.0.0.1:8765/api/booking/session',{headers,data:{}});
  assert.equal(fixture.status(),200);
  const session=(await fixture.json()).session_id;
  try {
    const offered=await page.request.post('http://127.0.0.1:8765/api/booking/search',{headers,data:{session_id:session,kind:'table',date,start_time:'18:00',party_size:6}});
    assert.equal(offered.status(),200);
    const offer=(await offered.json()).offers[0]; assert(offer,'fixture six-seat table was not available');
    const held=await page.request.post('http://127.0.0.1:8765/api/booking/prepare',{headers,data:{session_id:session,kind:'table',table_offer_id:offer.table_offer_id,guest_fixture_id:'guest-001'}});
    assert.equal(held.status(),200);
    const sent=posts.length;
    await fill(date,'18:00','6');
    assert.equal(posts.length,sent,'change handler automatically searched');
    assert.equal(await page.locator('.offer-button').count(),0,'changed fields retained old offers');
    const before=await fields(),empty=await search();
    await check('fully booked preserves six diners and offers a guest-chosen date/time',async()=>{
      assert.equal(empty.status,200); assert.deepEqual(empty.body.offers,[],'zero availability did not come from the actual adapter');
      const feedback=await page.locator('#new-booking-status').textContent();
      assert.match(feedback,/kuupäev/i); assert.match(feedback,/kellaaeg/i,'fully booked guidance omitted another time');
      assert.doesNotMatch(feedback,/või külaliste arvu/i,'fully booked guidance still suggests reducing the real party');
      assert.equal(await page.locator('#new-booking-status').evaluate(node=>node.classList.contains('error')),false);
      assert.deepEqual(await fields(),before,'no availability silently changed the requested party or time');
      assert.equal(posts.slice(sent).filter(post=>post.path==='/api/booking/search').length,1,'zero availability repeated the search');
      assert.equal(posts.slice(sent).filter(post=>post.path!=='/api/booking/search').length,0,'zero availability made another action');
      assert.equal(await page.locator('.offer-button').count(),0);
      assert.equal(await page.locator('#booking-recap').isHidden(),true);
    });
    await page.setViewportSize({width:390,height:844});
    await page.locator('#new-booking-section').screenshot({path:'output/playwright/restaurant-guest-unavailable-390.png'});
    await check('only a guest change and another click searches a different time',async()=>{
      const sent=posts.length;
      await page.locator('#new-start-time').fill('20:00'); await page.locator('#new-start-time').dispatchEvent('change');
      assert.equal(posts.length,sent,'changing time silently searched again');
      assert.equal(await page.locator('#new-party-size').inputValue(),'6');
      const result=await search(); assert.equal(result.status,200); assert(result.body.offers.length>0);
      const request=posts.at(-1).body;
      assert.equal(request.date,date); assert.equal(request.start_time,'20:00'); assert.equal(request.party_size,6);
      assert.equal(posts.length,sent+1,'guest retry made an extra action');
      assert.equal(await page.locator('#booking-recap').isHidden(),true);
    });
    for(const [name,status,body] of [
      ['backend failure differs from zero availability',503,{error:'fixture_backend_unavailable'}],
      ['malformed availability cannot invent an offer',200,{kind:'table',offers:null}],
      ['unknown availability cannot invent an offer',200,{kind:'unknown',offers:[]}],
    ]) {
      await page.route('**/api/booking/search',route=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)}));
      await check(name,async()=>{
        const before=await fields(),sent=posts.length;
        await search();
        const feedback=await page.locator('#new-booking-status').textContent();
        assert.equal(await page.locator('#new-booking-status').evaluate(node=>node.classList.contains('error')),true,'failed read was presented as an empty available day');
        assert.notEqual(feedback,''); assert.doesNotMatch(feedback,/Sellele valikule saadavust ei leitud/);
        assert.equal(await page.locator('.offer-button').count(),0,'failed read retained or invented an offer');
        assert.equal(await page.locator('#booking-recap').isHidden(),true);
        assert.deepEqual(await fields(),before,'failed read changed guest preferences');
        assert.equal(posts.length,sent+1,'failed read automatically repeated or mutated');
      });
      await page.unroute('**/api/booking/search');
    }
  } finally {
    const ended=await page.request.delete('http://127.0.0.1:8765/api/demo/session/'+session,{headers});
    assert.equal(ended.status(),200,'synthetic fixture session was not closed');
  }
  const examples={
    et:{incomplete:['Puuduv kellaaeg','Palun broneeri homme laud neljale inimesele.'],dietary:['Toitumise erisoov','Kas menüüs on gluteenivabu roogi?']},
    en:{incomplete:['Missing time','Please reserve a table for four tomorrow.'],dietary:['Dietary question','Are there gluten-free dishes on the menu?']},
  };
  for(const language of ['et','en']) {
    await page.locator('#demo-language').selectOption(language);
    await page.locator('#demo-start').click(); await page.waitForFunction(()=>state.sessionId && !state.turnBusy);
    for(const [key,[label,text]] of Object.entries(examples[language])) {
      await check(language+' '+key+' example sends its real value and shows only the server reply',async()=>{
        const button=page.locator('[data-demo-example="'+key+'"]');
        assert.equal(await button.count(),1,'restaurant example is missing');
        assert.equal(await button.textContent(),label); assert.equal(await button.getAttribute('data-message'),text);
        const sent=posts.length,messages=await page.locator('#demo-messages li').count();
        const response=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/turn');
        await button.click(); const reply=await response,wire=await reply.text();
        // The real route streams NDJSON even with the buffered fixture speaker.
        const actual=reply.headers()['content-type']?.startsWith('application/x-ndjson') ? wire.trim().split('\n').map(line=>JSON.parse(line)).findLast(event=>event.type==='done') : JSON.parse(wire);
        assert(actual && typeof actual.reply==='string','server response had no completed reply');
        await page.waitForFunction(()=>!state.turnBusy);
        assert.equal(posts.slice(sent).filter(post=>post.path==='/api/turn').length,1,'example sent more than one turn');
        const request=posts.slice(sent).find(post=>post.path==='/api/turn').body;
        assert.equal(request.text,text); assert.equal(request.language,language);
        assert.equal(await page.locator('#demo-messages li').count(),messages+2,'client fabricated extra replies');
        assert.equal(await page.locator('#demo-messages .user-message span').last().textContent(),text);
        assert.equal(await page.locator('#demo-messages .assistant-message span').last().textContent(),actual.reply,'client invented an example answer');
        if(key==='incomplete')assert.match(actual.reply,language==='en' ? /what time/i : /kellaaj/i,'real server did not clarify the example\'s missing time');
      });
    }
    if(language==='en') {
      for(const width of [1440,390,320]) {
        await page.setViewportSize({width,height:900});
        const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
        assert(size.scroll<=size.width,'restaurant dashboard overflow: '+JSON.stringify(size)); layouts.push({page:'dashboard',...size});
        if(width!==320)await page.locator('#demo-section').screenshot({path:'output/playwright/restaurant-guest-examples-'+width+'.png'});
      }
    }
    await page.locator('#demo-end').click(); await page.waitForFunction(()=>!state.sessionId && !state.turnBusy);
  }
  assert.equal(posts.filter(post=>/^\/api\/booking\/(prepare|recap|confirm|cancel)$/.test(post.path)).length,0,'guest UX performed an unrequested booking action');
  await page.locator('#logout').click();
  await page.goto('http://127.0.0.1:8765/hotel',{waitUntil:'networkidle'});
  assert.equal(await page.locator('#menu-list li').count(),3,'real public menu fixture did not load');
  for(const width of [1440,390,320]) {
    await page.setViewportSize({width,height:900});
    await check('public menu caution visible at '+width,async()=>{
      const caution=page.locator('#menu-caution'); assert.equal(await caution.count(),1,'menu has no visible dietary/allergen caution');
      await caution.scrollIntoViewIfNeeded(); assert.equal(await caution.isVisible(),true);
      const text=await caution.textContent();
      for(const word of [/koostis/i,/allergeen/i,/ristsaastumi/i,/eridieedi/i,/kontrollimata/i,/enne söömist/i,/restoran/i,/ei ühenda päris töötajaga/i])assert.match(text,word);
      const menu=await page.locator('#menu').textContent(); assert.match(menu,/tellimusi, makseid/);
    });
    const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert(size.scroll<=size.width,'public menu overflow: '+JSON.stringify(size)); layouts.push({page:'public',...size});
    if(width!==320)await page.locator('#menu').screenshot({path:'output/playwright/restaurant-guest-menu-'+width+'.png'});
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior),'auto');
  await page.reload({waitUntil:'networkidle'});
  await page.keyboard.press('Tab'); assert.equal(await page.locator('.skip-link').evaluate(node=>node===document.activeElement),true);
  await page.keyboard.press('Enter'); assert.equal(await page.locator('#main').evaluate(node=>node===document.activeElement),true);
  for(const body of [{},{tables:null,rules:null}]) {
    await page.route('**/api/public/catalogue',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)}));
    await page.reload({waitUntil:'networkidle'});
    await check('malformed public catalogue '+JSON.stringify(body),async()=>{
      assert.equal(await page.locator('.table-card').count(),0,'malformed catalogue invented inventory');
      assert.match(await page.locator('#tables-status').textContent(),/Saadavus pole kinnitatud/);
      assert.equal(await page.locator('#menu-caution').isVisible(),true,'catalogue failure hid the food caution');
    });
    await page.unroute('**/api/public/catalogue');
  }
  assert(requests.every(url=>url.origin==='http://127.0.0.1:8765'),'browser contacted an external service');
  assert.deepEqual(errors,[],'browser page errors');
  assert.deepEqual(failures,[],'restaurant guest UX failures: '+JSON.stringify(failures));
  return {result:'passed',cases,layouts,errors,realZeroAvailability:true,fixtureSessionClosed:true};
}
