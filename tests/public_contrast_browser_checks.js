async (page) => {
  const assert=(condition,message)=>{if(!condition)throw new Error(message);};
  await page.goto('http://127.0.0.1:8765/hotel', {waitUntil:'networkidle'});
  const results=[];
  for(const width of [1440,390,320]) {
    await page.setViewportSize({width,height:900});
    const contrasts=await page.locator('.hero-copy > p, .hero-note > span:last-child, .section-heading > p, #menu-caution').evaluateAll(nodes=>{
      const rgba=value=>value.match(/[\d.]+/g).map(Number);
      const luminance=rgb=>rgb.slice(0,3).map(value=>{
        const channel=value/255;
        return channel<=.04045 ? channel/12.92 : ((channel+.055)/1.055)**2.4;
      }).reduce((sum,value,index)=>sum+value*[.2126,.7152,.0722][index],0);
      return nodes.map(node=>{
        const style=getComputedStyle(node), foreground=rgba(style.color);
        let parent=node,background;
        while(parent) {
          const color=rgba(getComputedStyle(parent).backgroundColor);
          if(color.length===3 || color[3]===1) {background=color;break;}
          parent=parent.parentElement;
        }
        if(!background)throw new Error('public text has no opaque background');
        const a=luminance(foreground),b=luminance(background);
        return {element:node.className || node.parentElement.className,fontSize:parseFloat(style.fontSize),ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
      });
    });
    assert(contrasts.length>=2,'public guest guidance missing');
    for(const text of contrasts) {
      assert(text.ratio>=4.5,`public guest guidance contrast ${text.ratio.toFixed(2)}:1 below 4.5:1 (${text.element}, ${text.fontSize}px, ${width}px viewport)`);
    }
    if(width===390)await page.screenshot({path:'output/playwright/public-guidance-390.png',fullPage:true});
    results.push({width,contrasts});
  }
  return {result:'passed',minimumContrast:4.5,layouts:results};
}
