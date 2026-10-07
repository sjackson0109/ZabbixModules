/** Actual Chromium DOM and accessibility smoke checks for the self-hosted renderer.
 * Run with Playwright installed externally; no runtime library is added to the widgets.
 */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.NE_CHROMIUM||undefined,args:process.env.NE_CHROMIUM?['--no-sandbox','--disable-dev-shm-usage']:[]});
 try {
  const page=await browser.newPage({viewport:{width:1500,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<!doctype html><html><head><title>Network Explorer browser fixture</title></head><body><div id="widget" class="ne-widget"></div></body></html>');
  await page.addStyleTag({path:path.join(__dirname,'../../frontend/neportpanel/assets/css/widget.css')});
  await page.addScriptTag({path:path.join(__dirname,'../../frontend/neportpanel/assets/js/runtime.js')});
  // Synthetic schema fixtures only; this test makes no vendor qualification claim.
  const payload={scope:{hostid:'101',layout:'24'},hosts:[{hostid:'101',name:'Fixture switch A',dashboard_url:'zabbix.php?action=host.dashboard.view&hostid=101'},{hostid:'102',name:'Fixture switch B',dashboard_url:'zabbix.php?action=host.dashboard.view&hostid=102'}],
   interfaces:Array.from({length:48},(_,i)=>({hostid:'101',uid:`port:${i+1}`,if_index:i+1,name:`Eth${i+1}`,description:i===0?'<img src=x onerror="window.injected=1">':'Fixture interface',physical:true,member:i<24?1:2,slot:0,port:i%24+1,admin_status:'up',oper_status:i===2?'down':'up',speed_bps:1e9,expected_speed_bps:i===1?1e10:null,itemid:String(1000+i)})),
   edges:[{id:'one',source:'101',target:'102',source_uid:'port:1',target_uid:'peer:1',source_endpoint:{hostid:'101',uid:'port:1'},target_endpoint:{hostid:'102',uid:'peer:1'},confidence:'high',freshness:'current',lag_id:'lag-one'},{id:'two',source:'101',target:'102',source_uid:'port:2',target_uid:'peer:2',lag_id:'lag-one',confidence:'high',freshness:'current'}],
   lags:[{hostid:'101',uid:'lag:1',name:'Fixture LAG',protocol:'lacp',members:[{interface_uid:'port:1'},{interface_uid:'port:2'}]}],
   quality:[{hostid:'101',dataset:'interfaces',status:'ok',freshness:'current',capability:{state:'supported'},observed_at:'2026-10-06T00:00:00Z',attempted_at:'2026-10-06T00:00:00Z',complete:true},{hostid:'101',dataset:'lldp',status:'partial',freshness:'stale',capability:{state:'partial'},observed_at:'2026-10-05T00:00:00Z',complete:false}],
   findings:[{hostid:'101',rule:'speed',severity:'info',title:'=Unsafe spreadsheet formula',interface_uid:'port:2',reason:'Intended speed observation.'},{hostid:'101',rule:'csv-fixture',severity:'info',title:' =Unsafe spreadsheet formula after space',reason:'Whitespace fixture.'}]};
  await page.evaluate(p=>{window.testPayload=p;window.testBroadcasts=[];window.NEWidgetRuntime.render(document.querySelector('#widget'),p,'ports',(h,i)=>window.testBroadcasts.push([h,i]));},payload);
  assert.equal(await page.locator('.ne-port').count(),48);
  await page.locator('.ne-port').first().click();
  assert.ok((await page.locator('.ne-drawer').innerText()).includes('<img src=x onerror='));
  assert.equal(await page.locator('.ne-drawer img').count(),0);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  assert.equal(await page.locator('.ne-port').first().getAttribute('aria-pressed'),'true');
  const link=page.getByRole('link',{name:'Fixture switch B'});assert.equal(await link.count(),1);assert.ok((await link.getAttribute('href')).includes('#ne='));
  await page.locator('.ne-port').first().focus();await page.keyboard.press('ArrowRight');assert.equal(await page.locator('.ne-port').nth(1).evaluate(e=>e===document.activeElement),true);
  for(const layout of ['48','mixed','stack','generic']){await page.getByRole('combobox',{name:'Physical layout'}).selectOption(layout);assert.equal(await page.locator('.ne-port').count(),48);}
  assert.ok((await page.locator('#widget').innerText()).includes('VLAN: not collected'));
  await page.evaluate(()=>window.NEWidgetRuntime.render(document.querySelector('#widget'),window.testPayload,'topology',(h,i)=>window.testBroadcasts.push([h,i])));
  assert.equal(await page.locator('svg .ne-node').count(),2);assert.equal(await page.locator('svg .ne-edge').count(),1);
  await page.getByRole('button',{name:'Expand LAG member links'}).click();assert.equal(await page.locator('svg .ne-edge').count(),2);
  await page.locator('svg .ne-node').first().focus();await page.keyboard.press('Enter');assert.ok((await page.locator('.ne-drawer').innerText()).includes('Fixture switch A'));
  await page.evaluate(()=>window.NEWidgetRuntime.render(document.querySelector('#widget'),window.testPayload,'quality'));
  assert.equal(await page.locator('tbody tr').count(),2);assert.ok((await page.locator('#widget').innerText()).includes('partial'));
  await page.evaluate(()=>window.NEWidgetRuntime.render(document.querySelector('#widget'),window.testPayload,'findings'));
  const downloadEvent=page.waitForEvent('download');await page.getByRole('button',{name:'Export filtered CSV'}).click();const download=await downloadEvent;
  const stream=await download.createReadStream();let csv='';for await(const chunk of stream)csv+=chunk.toString('utf8');assert.ok(csv.includes("'=Unsafe spreadsheet formula"));assert.ok(csv.includes("' =Unsafe spreadsheet formula after space"));
  assert.deepEqual(errors,[]);
  console.log('Chromium: physical layouts, safe detail rendering, keyboard navigation, peer context, LAG expansion, quality and CSV export passed.');
 }
 finally {await browser.close();}
})().catch(e=>{console.error(e.stack);process.exit(1);});
