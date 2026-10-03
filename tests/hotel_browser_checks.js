async (page) => {
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  const errors=[],requests=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>requests.push(request.url()));
  let phoneConfigured=false,catalogueFails=false,propertyFails=false,phoneNumber='+12025550109';
  const tables=[{id:'table-1',name:'Näidislaud <img>',capacity:2}];
  const rules={timezone:'Europe/Tallinn',opening_time:'12:00',closing_time:'22:00',duration_minutes:120,min_party_size:1,max_party_size:6,horizon_days:90,combine_tables:false,children_count_toward_party_size:true};
  await page.unroute('**/api/**');
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    const reply=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/public/property')return reply(propertyFails?{}:{synthetic:true,property:{name:'Meretuule restoran',description_et:'Fiktiivne restoran',timezone:'Europe/Tallinn',restaurant_rules:rules},phone:{configured:phoneConfigured,number:phoneConfigured?phoneNumber:null},faq:[{question_et:'Kas see on päris restoran?',answer_et:'Ei. See on fiktiivne demo.'}]},propertyFails?503:200);
    if(path==='/api/public/catalogue')return reply(catalogueFails?{}:{tables,rules,menu:[{name:'Demomenüü <img>',description_et:'Fiktiivne roog; tellimusi ei võeta vastu.'}]},catalogueFails?503:200);
    throw new Error('public website requested private endpoint: '+path);
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:8765/hotel');
  await page.waitForFunction(()=>document.querySelectorAll('.table-card').length===1);
  assert(await page.locator('#phone-number').isHidden(),'unconfigured phone was invented');
  assert((await page.locator('.table-card h3').textContent()).includes('<img>'),'provider table name was interpreted as markup');
  assert(await page.locator('.table-card img, #menu-list img').count()===0,'untrusted provider markup became an image');
  assert((await page.locator('#menu-list').textContent()).includes('Demomenüü <img>'),'restaurant menu was not rendered as text');
  assert((await page.locator('#opening-hours').textContent()).includes('12:00–22:00'),'restaurant opening hours disappeared');
  assert((await page.locator('#rules-list').textContent()).includes('120'),'authoritative sitting rule missing');
  assert((await page.locator('#rules-list').textContent()).includes('90'),'authoritative horizon rule missing');
  await page.getByText('Kas see on päris restoran?',{exact:true}).click();
  assert(await page.getByText('Ei. See on fiktiivne demo.',{exact:true}).isVisible(),'FAQ did not open');
  const layouts=[];
  for(const width of [1440,1024,768,700,390,320]){
    await page.setViewportSize({width,height:900});
    const size=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
    assert(size.scroll<=size.width,'restaurant overflow: '+JSON.stringify(size));layouts.push(size);
  }
  await page.emulateMedia({reducedMotion:'reduce'});
  assert(await page.evaluate(()=>getComputedStyle(document.documentElement).scrollBehavior)==='auto','restaurant ignored reduced motion');
  phoneConfigured=true;await page.reload();
  await page.waitForFunction(()=>!document.getElementById('phone-number').hidden);
  assert(await page.locator('#phone-number').getAttribute('href')==='tel:+12025550109','configured number not linked');
  const link=await page.locator('.table-card .text-link').getAttribute('href');
  assert(link==='https://robot.arleserver.cfd/?book=table','table booking lost the authenticated management domain');
  phoneNumber='javascript:fixture';await page.reload({waitUntil:'networkidle'});
  assert(await page.locator('#phone-number').isHidden(),'malformed configured phone became a link');
  assert(await page.locator('#phone-number').getAttribute('href')===null,'unverified phone retained a clickable href');
  propertyFails=true;await page.reload({waitUntil:'networkidle'});
  assert(await page.locator('#phone-number').isHidden(),'failed property read invented a phone');
  assert((await page.locator('#phone-status').textContent()).includes('ei saanud kontrollida'),'failed phone read was presented as configured');
  catalogueFails=true;await page.reload();
  await page.waitForFunction(()=>document.getElementById('tables-status').classList.contains('error'));
  assert(await page.locator('.table-card').count()===0,'failed provider read invented table inventory');
  assert(await page.locator('#menu-list li, #rules-list li').count()===0,'failed catalogue read invented menu or rules');
  assert(requests.every(url=>new URL(url).hostname==='127.0.0.1'),'restaurant made external browser request');
  assert(errors.length===0,'restaurant browser errors: '+errors.join('; '));
  await page.unroute('**/api/**');
  return {result:'passed',layouts,phoneCases:4,providerFailure:true,errors};
}
