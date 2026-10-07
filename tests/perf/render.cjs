/** Browser render budget at the spec's scale: draws the Topology widget from the payload tests/perf/scale.php writes.
 * Usage: php -d memory_limit=2G tests/perf/scale.php 1 /tmp/scale.json && node tests/perf/render.cjs /tmp/scale.json [runs]
 * Synthetic data only. Measures parse plus render in Chromium, not network transfer or Zabbix API latency.
 */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const file=process.argv[2],runs=Number(process.argv[3]||5);if(!file)throw new Error('Pass the payload written by scale.php');
const payload=fs.readFileSync(file,'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.NE_CHROMIUM||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const times=[];let counts;
  for(let r=0;r<runs;++r){
   const page=await browser.newPage({viewport:{width:1700,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.setContent('<!doctype html><html><head><title>Network Explorer render budget</title></head><body><div id="widget" class="ne-widget"></div></body></html>');
   await page.addStyleTag({path:path.join(__dirname,'../../src/widget/widget.css')});
   await page.addScriptTag({path:path.join(__dirname,'../../src/widget/runtime.js')});
   const result=await page.evaluate(text=>new Promise(resolve=>{const start=performance.now();const data=JSON.parse(text);
    window.NEWidgetRuntime.render(document.querySelector('#widget'),data,'topology',()=>{});
    // Two frames: the first lays out, the second has painted.
    requestAnimationFrame(()=>requestAnimationFrame(()=>resolve({ms:performance.now()-start,nodes:document.querySelectorAll('svg .ne-node').length,edges:document.querySelectorAll('svg .ne-edge').length})));}),payload);
   if(errors.length)throw new Error(errors.join('\n'));
   times.push(result.ms);counts=result;await page.close();
  }
  times.sort((a,b)=>a-b);
  console.log(`nodes=${counts.nodes} edges=${counts.edges}; first render ms: median=${times[Math.floor(runs/2)].toFixed(0)} max=${times[runs-1].toFixed(0)} over ${runs} runs`);
 }
 finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exit(1);});
