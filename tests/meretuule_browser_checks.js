async (page) => {
  // Removing the domain's website route must fail this real-browser acceptance check.
  const tab = await page.context().newPage();
  const require = (ok, message) => { if (!ok) throw new Error(message); };
  const errors = [];
  tab.on('pageerror', error => errors.push(error.message));
  try {
    const legacyRedirects = [];
    for (const [path, destination] of [
      ['/hotel', 'https://meretuule.arleserver.cfd/'],
      ['/hotel/', 'https://meretuule.arleserver.cfd/'],
      ['/hotel?via=old-demo', 'https://meretuule.arleserver.cfd/?via=old-demo'],
    ]) {
      const url = `https://robot.arleserver.cfd${path}`;
      const redirect = await tab.request.get(url, {maxRedirects: 0});
      require(redirect.status() === 301, `Legacy hotel returned ${redirect.status()}, expected permanent redirect: ${path}`);
      require(redirect.headers().location === destination, `Wrong hotel redirect destination: ${path}`);
      await tab.goto(url, {waitUntil: 'networkidle', timeout: 30000});
      require(tab.url() === destination && /restoran|restaurant|ресторан/i.test(await tab.title()), `Legacy hotel redirect loop or wrong site: ${path}`);
      legacyRedirects.push({path, status: redirect.status(), destination});
    }
    const response = await tab.goto('https://meretuule.arleserver.cfd/', {
      waitUntil: 'networkidle', timeout: 30000,
    });
    require(response?.status() === 200, `Meretuule root returned ${response?.status()}, expected 200`);
    const title = await tab.title();
    const headings = await tab.locator('h1').allTextContents();
    require(/restoran|restaurant|ресторан/i.test(title), `Restaurant reception did not load: ${title}`);
    require(tab.url() === 'https://meretuule.arleserver.cfd/', 'Website root redirected elsewhere');
    const homepageLinks = await tab.locator('a.demo-website-link').evaluateAll(elements =>
      elements.map(el => el.getAttribute('href'))
    );
    require(homepageLinks.length === 2 && homepageLinks.every(href => href === 'https://meretuule.arleserver.cfd/'), 'Website homepage links did not use the exact canonical Meretuule root');
    const urls = await tab.locator('script[src], link[rel="stylesheet"][href], link[as="font"][href], img[src]').evaluateAll(elements =>
      [...new Set(elements.map(el => el.src || el.href))]
    );
    const assets = [];
    for (const url of urls) {
      if (new URL(url).origin !== 'https://meretuule.arleserver.cfd') continue;
      const asset = await tab.request.get(url);
      require(asset.status() === 200, `Asset returned ${asset.status()}: ${url}`);
      const content = await asset.body();
      const sha256 = await tab.evaluate(async bytes => {
        const hash = await crypto.subtle.digest('SHA-256', new Uint8Array(bytes));
        return [...new Uint8Array(hash)].map(value => value.toString(16).padStart(2, '0')).join('');
      }, [...content]);
      const version = new URL(url).searchParams.get('v');
      if (version) require(sha256.slice(0, 12) === version, `Stale versioned asset: ${url}`);
      assets.push({url, status: asset.status(), bytes: content.length, sha256});
    }
    await tab.waitForFunction(() => document.querySelectorAll('#menu-list li').length > 0);
    require(await tab.locator('#restaurant-name').textContent() === 'Meretuule Demo Restaurant', 'Published restaurant name did not load');
    require((await tab.locator('#opening-hours').textContent()).length > 0, 'Restaurant opening hours did not load');
    require((await tab.locator('#restaurant-policies').textContent()).length > 0, 'Restaurant policies did not load');
    require(await tab.locator('#reservation-prepare').isDisabled(), 'Unauthenticated reservation controls are active');
    const information = await tab.request.get('https://meretuule.arleserver.cfd/api/public/restaurant');
    const property = await information.json();
    require(information.status() === 200 && property.business_type === 'restaurant' && property.synthetic === true, 'Public data is not the restaurant business');
    for (const host of ['meretuule.arleserver.cfd', 'robot.arleserver.cfd']) {
      const denied = await tab.request.get(`https://${host}/api/bookings`);
      require(denied.status() === 403, `${host} exposed private bookings`);
      require(denied.headers()['cache-control'] === 'no-store', `${host} cached an authorization failure`);
    }
    const robot = await tab.request.get('https://robot.arleserver.cfd/');
    const robotHtml = await robot.text();
    require(robot.status() === 200 && robotHtml.includes('id="reservation-prepare"') && robotHtml.includes('id="operator-token"'), 'Robot root no longer serves restaurant management');
    const dashboardRestaurantLinks = await tab.evaluate(html =>
      [...new DOMParser().parseFromString(html, 'text/html').querySelectorAll('a.demo-website-link')].map(el => el.getAttribute('href')),
    robotHtml);
    require(dashboardRestaurantLinks.length === 2 && dashboardRestaurantLinks.every(href => href === 'https://meretuule.arleserver.cfd/'), 'Management restaurant links did not use the exact canonical Meretuule root');
    const health = await tab.request.get('https://robot.arleserver.cfd/health');
    require(health.status() === 200 && (await health.json()).ok === true, 'Robot health check failed');
    const management = await page.context().newPage();
    management.on('pageerror', error => errors.push(error.message));
    try {
      for (const index of [0, 1]) {
        await management.goto('https://robot.arleserver.cfd/', {waitUntil: 'networkidle', timeout: 30000});
        const demoLinks = management.locator('a.demo-website-link');
        require(await demoLinks.count() === 2, 'Management demo links do not point directly to the public root');
        await demoLinks.nth(index).click();
        await management.waitForURL('https://meretuule.arleserver.cfd/');
        require(/restoran|restaurant|ресторан/i.test(await management.title()), 'Management demo link did not open the restaurant website');
      }
    } finally { await management.close(); }
    require(errors.length === 0, `Website browser errors: ${errors.join('; ')}`);
    return {pass: true, url: tab.url(), status: response.status(), title, headings, assets,
      menuItems: await tab.locator('#menu-list li').count(), tables: property.restaurant.tables.length,
      homepageLinks, dashboardRestaurantLinks, legacyRedirects, dashboardDemoLinkVerified: true, dashboardDemoLinksVerified: 2,
      privateRoutesDenied: true, robotHealthy: true, errors};
  } finally {
    await tab.close();
  }
}
