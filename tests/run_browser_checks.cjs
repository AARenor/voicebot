// Installed Playwright + project Python only; no package installation or live APIs.
// node tests/run_browser_checks.cjs /path/to/playwright /path/to/python [check.js ...]
const fs=require('node:fs'), path=require('node:path'), net=require('node:net');
const {spawn}=require('node:child_process');
const {chromium}=require(process.argv[2] || 'playwright');
const root=path.resolve(__dirname,'..');
process.chdir(root);
const available=['dashboard_browser_checks.js','booking_browser_checks.js','hotel_browser_checks.js','voice_browser_checks.js','microphone_race_browser_checks.js','english_demo_browser_checks.js','modern_voice_browser_checks.js','streaming_voice_browser_checks.js','restaurant_browser_checks.js','restaurant_public_browser_checks.js'];
const checks=process.argv.slice(4);
if(!checks.length)checks.push(...available);
if(checks.some(name=>!available.includes(name)))throw new Error('expected a local browser check filename');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  const channel=process.env.PLAYWRIGHT_BROWSER_CHANNEL;
  if(channel && !['chrome','msedge','chromium'].includes(channel))throw new Error('unknown browser channel');
  const fixtures=[];
  let browser;
  const startFixture=async factory=>{
    const probe=net.createServer();
    await new Promise((resolve,reject)=>{probe.once('error',reject);probe.listen(0,'127.0.0.1',resolve);});
    const port=probe.address().port;
    await new Promise(resolve=>probe.close(resolve));
    const origin=`http://127.0.0.1:${port}`;
    const server=spawn(process.argv[3] || 'python3',['-m','uvicorn',factory.includes(':') ? factory : `tests.browser_fixture:${factory}`,'--factory','--host','127.0.0.1','--port',String(port),'--no-access-log'],{
      cwd:root,env:{PATH:process.env.PATH,SystemRoot:process.env.SystemRoot,TEMP:process.env.TEMP,TMP:process.env.TMP,PYTHONDONTWRITEBYTECODE:'1',VOICEBOT_BUSINESS_TYPE:'hotel_spa'},stdio:['ignore','ignore','pipe']
    });
    const fixture={server,origin}; fixtures.push(fixture);
    let serverErrors='', spawnError=null;
    server.stderr.on('data',chunk=>{serverErrors=(serverErrors+chunk).slice(-4000);});
    server.on('error',error=>{spawnError=error;});
    for(let i=0;i<100;i++){
      try{if((await fetch(origin+'/api/status',{signal:AbortSignal.timeout(1000)})).ok)return fixture;}catch(_){}
      if(spawnError || server.exitCode!==null)break;
      await sleep(100);
    }
    throw new Error(`local ${factory} fixture did not start: `+(spawnError?.message || serverErrors));
  };
  try {
    const regular=await startFixture('create_app');
    const streaming=checks.includes('streaming_voice_browser_checks.js') ? await startFixture('create_streaming_app') : regular;
    const restaurant=checks.some(name=>name.startsWith('restaurant_')) ? await startFixture('tests.restaurant_browser_fixture:create_app') : regular;
    fs.mkdirSync(path.join(root,'output/playwright'),{recursive:true});
    browser=await chromium.launch({headless:true,...(channel?{channel}:{})});
    for(const name of checks){
      const origin=name.startsWith('restaurant_') ? restaurant.origin : name==='streaming_voice_browser_checks.js' ? streaming.origin : regular.origin;
      const context=await browser.newContext({serviceWorkers:'block'}), external=[];
      await context.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin!==origin && url.protocol!=='blob:'){external.push(url.origin);return route.abort('blockedbyclient');}return route.continue();});
      const page=await context.newPage();
      let timer;
      try {
        const check=eval('('+fs.readFileSync(path.join(__dirname,name),'utf8').replaceAll('http://127.0.0.1:8765',regular.origin).replaceAll('http://127.0.0.1:8776',streaming.origin).replaceAll('http://127.0.0.1:8766',restaurant.origin)+')');
        const result=await Promise.race([check(page),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(`${name}: browser check timed out`)),120000);})]);
        if(external.length)throw new Error('browser tried an external request');
        console.log(JSON.stringify({check:name,...result,externalRequests:external,browser:browser.version()}));
      } catch(error) {console.error(JSON.stringify({check:name,result:'failed',error:error.message}));process.exitCode=1;}
      finally {clearTimeout(timer);await context.close();}
    }
  } finally {
    if(browser)await browser.close();
    await Promise.all(fixtures.map(async({server})=>{if(server.pid && server.exitCode===null && server.signalCode===null){server.kill('SIGTERM');await new Promise(resolve=>server.once('exit',resolve));}}));
  }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
