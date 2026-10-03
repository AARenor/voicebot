async (page) => {
  // Removing the domain's website route must fail this real-browser acceptance check.
  const tab = await page.context().newPage();
  const require = (ok, message) => { if (!ok) throw new Error(message); };
  const errors = [];
  tab.on('pageerror', error => errors.push(error.message));
  try {
    const response = await tab.goto('https://meretuule.arleserver.cfd/', {
      waitUntil: 'networkidle', timeout: 30000,
    });
    require(response?.status() === 200, `Meretuule root returned ${response?.status()}, expected 200`);
    const title = await tab.title();
    const headings = await tab.locator('h1').allTextContents();
    require(/Meretuule/i.test(title), `Website title missing Meretuule: ${title}`);
    require(!/Vastuvõtulaud/i.test(title), 'Public domain served the operator dashboard');
    require(tab.url() === 'https://meretuule.arleserver.cfd/', 'Website root redirected elsewhere');
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
    await tab.waitForFunction(() => document.querySelectorAll('.room-card').length > 0);
    require(await tab.locator('#service-list li').count() > 0, 'Public spa catalogue did not load');
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
    require(robot.status() === 200 && (await robot.text()).includes('<title>Vastuvõtulaud'), 'Robot root no longer serves the operator dashboard');
    const health = await tab.request.get('https://robot.arleserver.cfd/health');
    require(health.status() === 200 && (await health.json()).ok === true, 'Robot health check failed');
    require(errors.length === 0, `Website browser errors: ${errors.join('; ')}`);
    return {pass: true, url: tab.url(), status: response.status(), title, headings, assets,
      rooms: await tab.locator('.room-card').count(), services: await tab.locator('#service-list li').count(),
      operatorLinks, privateRoutesDenied: true, robotHealthy: true, errors};
  } finally {
    await tab.close();
  }
}
