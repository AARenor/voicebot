// Run with already-installed Playwright; no frontend dependency is required.
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const available = ['dashboard_browser_checks.js', 'hotel_browser_checks.js', 'booking_browser_checks.js', 'voice_browser_checks.js', 'microphone_race_browser_checks.js', 'english_demo_browser_checks.js', 'modern_voice_browser_checks.js', 'streaming_voice_browser_checks.js'];
(async()=>{
  fs.mkdirSync(path.join(root,'output/playwright'),{recursive:true});
  process.chdir(root);
  const channel=process.env.PLAYWRIGHT_BROWSER_CHANNEL;
  if (channel && !['chrome','msedge','chromium'].includes(channel)) throw new Error('unknown browser channel');
  const browser = await chromium.launch({headless:true,...(channel ? {channel} : {})});
  try {
    for (const name of process.argv.length > 2 ? process.argv.slice(2) : available) {
      if (!available.includes(name)) throw new Error('unknown browser check');
      const page = await browser.newPage();
      try {
        const check = eval('('+fs.readFileSync(path.join(__dirname,name),'utf8')+')');
        console.log(JSON.stringify({check:name,...await check(page)}));
      } finally {await page.close();}
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
