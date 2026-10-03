async (page) => {
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>requests.push(request.url()));
  let phoneConfigured=false,catalogueFails=false;
  const rooms=[{id:'fixture-room',name:'Näidistuba <img>',description:'Fiktiivne toatüüp',capacity:2,amenities:['Dušš','Wi-Fi']}];
  await page.unroute('**/api/**');
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    const reply=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/public/property')return reply({synthetic:true,property:{name:'Meretuule Demo Spa',description_et:'Fiktiivne spaahotell',timezone:'Europe/Tallinn',hours_scope:'spa_treatments',working_hours:{monday:{start:'09:00',end:'17:00',breaks:[{start:'12:00',end:'13:00'}]},sunday:null}},phone:{configured:phoneConfigured,number:phoneConfigured?'+12025550109':null},faq:[{question_et:'Kas see on päris spaa?',answer_et:'Ei. See on fiktiivne demo.'}]});
    if(path==='/api/public/catalogue')return reply(catalogueFails?{}:{services:[{id:1,name:'Demo spaakonsultatsioon',duration:30}],rooms:{room_types:rooms}},catalogueFails?503:200);
    throw new Error('public website requested private endpoint: '+path);
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:8765/hotel');
  await page.waitForFunction(()=>document.querySelectorAll('.room-card').length===1);
  assert(await page.locator('#phone-number').isHidden(),'unconfigured phone was invented');
  assert((await page.locator('.room-card h3').textContent()).includes('<img>'),'provider room name was interpreted as markup');
  assert(await page.locator('.room-card img').count()===0,'untrusted provider markup became an image');
  assert((await page.locator('#opening-hours').textContent()).includes('09:00–12:00, 13:00–17:00'),'provider lunch break disappeared');
  await page.getByText('Kas see on päris spaa?',{exact:true}).click();
  assert(await page.getByText('Ei. See on fiktiivne demo.',{exact:true}).isVisible(),'FAQ did not open');
  const layouts=[];
  for(const width of [1440,1024,768,700,390,320]){
    await page.setViewportSize({width,height:900});
    const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert(size.scroll<=size.width,'hotel overflow: '+JSON.stringify(size));layouts.push(size);
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  assert(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior)==='auto','hotel ignored reduced motion');
  phoneConfigured=true;await page.reload();
  await page.waitForFunction(()=>!document.getElementById('phone-number').hidden);
  assert(await page.locator('#phone-number').getAttribute('href')==='tel:+12025550109','configured number not linked');
  const link=await page.locator('.room-card .text-link').getAttribute('href');
  assert(link==='https://robot.arleserver.cfd/?book=stay&room=fixture-room','room booking did not preserve the management domain and selected room');
  catalogueFails=true;await page.reload();
  await page.waitForFunction(()=>document.getElementById('rooms-status').classList.contains('error'));
  assert(await page.locator('.room-card').count()===0,'failed provider read invented room inventory');
  assert(requests.every(url=>new URL(url).hostname==='127.0.0.1'),'hotel made external browser request');
  assert(errors.length===0,'hotel browser errors: '+errors.join('; '));
  await page.unroute('**/api/**');
  return {result:'passed',layouts,phoneCases:2,providerFailure:true,errors};
}
