async (page) => {
  const require = (ok,message) => { if(!ok) throw new Error(message); };
  const errors=[], layouts=[];
  page.on('pageerror', error=>errors.push(error.message));
  const origin='http://127.0.0.1:8766';
  await page.goto(origin+'/hotel',{waitUntil:'networkidle'});
  require(await page.title()==='Meretuule — restorani demo','Public renderer is not the restaurant');
  require(await page.locator('.table-card').count()>0,'Table catalogue did not load');
  require(await page.locator('#menu-list li').count()>0,'Fictional menu did not load');
  require(await page.locator('#opening-hours li').count()===7,'Weekly restaurant hours did not load');
  require((await page.locator('#allergy-notice').textContent()).length>0,'Allergy uncertainty is missing');
  const links=await page.locator('a[href]').evaluateAll(elements=>elements.map(el=>el.getAttribute('href')));
  require(links.filter(href=>href==='https://meretuule.arleserver.cfd/').length===2,'Wrong canonical homepage');
  require(links.includes('https://robot.arleserver.cfd/?book=table') && links.includes('https://robot.arleserver.cfd/#demo-section'),'Wrong booking or voice destination');
  for(const width of [1440,1024,768,700,390,320]) {
    await page.setViewportSize({width,height:1000});
    const scroll=await page.evaluate(()=>document.documentElement.scrollWidth);
    require(scroll<=width,`Public restaurant overflow at ${width}`); layouts.push({width,scroll});
  }
  await page.screenshot({path:'output/playwright/restaurant-public-mobile.png',fullPage:true});
  await page.route('**/api/public/restaurant',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({synthetic:true,business_type:'restaurant',restaurant:{description:{et:'<img src=x onerror=alert(1)>'},allergy_notice:{et:'Unverified allergy safety'},tables:[{name:'<img src=x onerror=alert(1)>',capacity:2}],menu:[{name:{et:'<script>alert(1)</script>'}}],opening_hours:{monday:{start:'12:00',end:'20:00'}},policies:{et:'Synthetic policies'},reservation_duration_minutes:90,maximum_party_size:8,advance_days:30}})}));
  await page.reload({waitUntil:'networkidle'});
  require((await page.locator('.table-card h3').textContent()).includes('<img'),'Provider table text was not displayed safely');
  require(await page.locator('#table-grid img, #menu-list script').count()===0,'Provider text became executable markup');
  await page.unroute('**/api/public/restaurant');
  await page.route('**/api/public/restaurant',route=>route.fulfill({status:503,body:'unavailable'}));
  await page.reload({waitUntil:'networkidle'});
  require(await page.locator('.table-card, #menu-list li').count()===0,'Failed public reads advertised stale capacity/menu');
  require((await page.locator('#tables-status').textContent()).includes('Saadavus pole kinnitatud'),'Unavailable catalogue has no honest recovery');
  require(errors.length===0,'Public page script errors: '+errors.join(';'));
  return {result:'passed',layouts,canonicalLinks:true,unsafeProviderTextEscaped:true,providerFailureClosed:true,errors};
}
