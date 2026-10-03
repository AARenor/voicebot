async (page) => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const errors = [], requests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => requests.push(request.url()));
  await page.setViewportSize({width: 1440, height: 1000});
  await page.goto('http://127.0.0.1:8765/hotel');
  assert(/Meretuule Köök/.test(await page.title()), 'restaurant title is missing');
  assert(await page.locator('.menu-item').count() === 4, 'sample menu is incomplete');
  assert(await page.locator('#faq-list details').count() === 4, 'restaurant FAQ did not render');
  assert((await page.locator('#hours-status').textContent()).includes('pole demo jaoks kinnitatud'), 'restaurant hours were claimed');
  assert((await page.locator('#phone-status').textContent()).includes('Päris restoraninumbrit pole seadistatud'), 'restaurant phone was claimed');
  assert((await page.locator('.menu-note').textContent()).includes('allergeeniteave'), 'sample menu disclosure is missing');
  await page.getByText('Kas Meretuule Köök on päris restoran?', {exact: true}).click();
  assert(await page.getByText('Ei. See on restoranidele mõeldud väljamõeldud tooteesitlus.', {exact: true}).isVisible(), 'fictional restaurant FAQ did not open');
  const layouts = [];
  for (const width of [1440, 1024, 768, 700, 390, 320]) {
    await page.setViewportSize({width, height: 900});
    const size = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
    assert(size.scroll <= size.width, 'restaurant page overflow: ' + JSON.stringify(size));
    layouts.push(size);
  }
  await page.emulateMedia({reducedMotion: 'reduce'});
  assert(await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior) === 'auto', 'restaurant page ignored reduced motion');
  const homeLinks = await page.locator('a.wordmark, a.footer-brand').evaluateAll(items => items.map(item => item.href));
  assert(homeLinks.length === 2 && homeLinks.every(href => href === 'https://meretuule.arleserver.cfd/'), 'restaurant home links are not canonical');
  const demoLinks = await page.locator('a[href*="robot.arleserver.cfd"]').evaluateAll(items => items.map(item => item.href));
  assert(demoLinks.length >= 3 && demoLinks.every(href => new URL(href).hostname === 'robot.arleserver.cfd'), 'restaurant assistant links left the robot domain');
  assert(requests.every(url => new URL(url).hostname === '127.0.0.1'), 'restaurant page made external browser request');
  assert(errors.length === 0, 'restaurant page browser errors: ' + errors.join('; '));
  return {result: 'passed', layouts, menuItems: 4, faqItems: 4, errors};
}
