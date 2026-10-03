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
      require(tab.url() === destination && /Meretuule/.test(await tab.title()), `Legacy hotel redirect loop or wrong site: ${path}`);
      legacyRedirects.push({path, status: redirect.status(), destination});
    }
    const response = await tab.goto('https://meretuule.arleserver.cfd/', {
      waitUntil: 'networkidle', timeout: 30000,
    });
    require(response?.status() === 200, `Meretuule root returned ${response?.status()}, expected 200`);
    const title = await tab.title();
    const headings = await tab.locator('h1').allTextContents();
    require(/Meretuule/i.test(title), `Website title missing Meretuule: ${title}`);
    require(!/Vastuvõtulaud/i.test(title), 'Public domain served the operator dashboard');
    require(tab.url() === 'https://meretuule.arleserver.cfd/', 'Website root redirected elsewhere');
    const homepageLinks = await tab.locator('a.wordmark, a.footer-brand').evaluateAll(elements =>
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
    require(await tab.locator('.menu-item').count() === 4, 'Restaurant sample menu is incomplete');
    require(await tab.locator('#faq-list details').count() === 4, 'Restaurant demo FAQ did not render');
    require(await tab.locator('#hours-status').textContent().then(text => /pole demo jaoks kinnitatud/i.test(text)), 'Restaurant hours were presented as configured');
    const operatorLinks = await tab.locator('a[href]').evaluateAll(elements =>
      elements.filter(el => /book=|demo-section/.test(el.href) || /operaatori töölaud/i.test(el.textContent || '')).map(el => el.href)
    );
    require(operatorLinks.length > 0, 'Website is missing its management links');
    require(operatorLinks.every(href => new URL(href).origin === 'https://robot.arleserver.cfd'), 'A management link stayed on the public website');
    for (const host of ['meretuule.arleserver.cfd', 'robot.arleserver.cfd']) {
      const denied = await tab.request.get(`https://${host}/api/bookings`);
      require(denied.status() === 403, `${host} exposed private bookings`);
      require(denied.headers()['cache-control'] === 'no-store', `${host} cached an authorization failure`);
    }
    const robot = await tab.request.get('https://robot.arleserver.cfd/');
    const robotHtml = await robot.text();
    require(robot.status() === 200 && robotHtml.includes('<title>Restorani vastuvõtulaud'), 'Robot root no longer serves the operator dashboard');
    const dashboardHotelLinks = await tab.evaluate(html =>
      [...new DOMParser().parseFromString(html, 'text/html').querySelectorAll('a.hotel-link, .heading-actions a.button:not(.primary)')].map(el => el.getAttribute('href')),
    robotHtml);
    require(dashboardHotelLinks.length === 2 && dashboardHotelLinks.every(href => href === 'https://meretuule.arleserver.cfd/'), 'Dashboard hotel links did not use the exact canonical Meretuule root');
    const health = await tab.request.get('https://robot.arleserver.cfd/health');
    require(health.status() === 200 && (await health.json()).ok === true, 'Robot health check failed');
    const management = await page.context().newPage();
    try {
      await management.goto('https://robot.arleserver.cfd/', {waitUntil: 'networkidle', timeout: 30000});
      const demoLinks = management.locator('a[href="https://meretuule.arleserver.cfd/"]');
      require(await demoLinks.count() === 2, 'Dashboard demo links do not point directly to the public root');
      await demoLinks.first().click();
      await management.waitForURL('https://meretuule.arleserver.cfd/');
      require(/Meretuule/.test(await management.title()), 'Dashboard demo link did not open the restaurant website');
    } finally { await management.close(); }
    require(errors.length === 0, `Website browser errors: ${errors.join('; ')}`);
    return {pass: true, url: tab.url(), status: response.status(), title, headings, assets,
      menuItems: await tab.locator('.menu-item').count(), faqItems: await tab.locator('#faq-list details').count(),
      homepageLinks, dashboardHotelLinks, operatorLinks, legacyRedirects, dashboardDemoLinkVerified: true,
      privateRoutesDenied: true, robotHealthy: true, errors};
  } finally {
    await tab.close();
  }
}
