/** LAB ONLY: the spec's acceptance walkthrough (docs/design/07-test-plan.md) against the native SNMP lab.
 * Prerequisites, per version: lab.py start, an SNMP simulator serving tests/fixtures/walks, then
 * native_snmp.py import, hosts, poll; lab.py install-modules; native_snmp.py dashboard and viewer.
 * Usage: node lab/acceptance.cjs 7.0 [--outage]   (--outage expects sw-access-17 broken via native_snmp.py break)
 * Reads generated lab credentials only and never prints them.
 */
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const version=process.argv[2]||'7.0',outage=process.argv.includes('--outage');
const port={'7.0':18070,'7.2':18072,'7.4':18074}[version];if(!port)throw new Error('Unsupported lab version');
const url=`http://127.0.0.1:${port}`,state=path.join(__dirname,'.state',version);
const admin=JSON.parse(fs.readFileSync(path.join(state,'credentials.json'))).admin;
const viewer=JSON.parse(fs.readFileSync(path.join(state,'viewer.json')));
const HIDDEN=['sw-dist-01','10.102.5.10'];
async function api(method,params,token){const r=await fetch(url+'/api_jsonrpc.php',{method:'POST',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:JSON.stringify({jsonrpc:'2.0',id:1,method,params})});const b=await r.json();if(b.error)throw new Error(method+': '+JSON.stringify(b.error));return b.result;}
async function login(browser,username,password){
 const page=await (await browser.newContext({viewport:{width:1700,height:1200}})).newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url+'/index.php');await page.locator('#name').fill(username);await page.locator('#password').fill(password);await page.locator('#enter').click();await page.waitForURL(/zabbix\.php/,{timeout:30000});
 return {page,errors};
}
const steps=[];const step=(name)=>{steps.push(name);console.log('ok',steps.length,name);};
(async()=>{
 const token=await api('user.login',{username:'Admin',password:admin});
 const hosts=Object.fromEntries((await api('host.get',{output:['hostid','host'],filter:{host:['sw-core-01','sw-access-17','sw-dist-01','sw-dist-02','sw-stack-01']}},token)).map(h=>[h.host,h.hostid]));
 assert.equal(Object.keys(hosts).length,5,'Create the five lab switches first');
 // A shared fleet dashboard: topology with the management subnet, and findings.
 let fleet=(await api('dashboard.get',{output:['dashboardid'],filter:{name:'Network Explorer fleet (lab)'}},token))[0]?.dashboardid;
 if(!fleet)fleet=(await api('dashboard.create',{name:'Network Explorer fleet (lab)',private:0,display_period:30,auto_start:0,
  userGroups:[],users:[],pages:[{widgets:[
   {type:'netopology',name:'Topology',x:0,y:0,width:72,height:12,fields:[{type:1,name:'management_cidr',value:'10.101.0.0/16'}]},
   {type:'nefindings',name:'Findings',x:0,y:12,width:72,height:7,fields:[]}]}]},token)).dashboardids[0];
 const browser=await chromium.launch({headless:true,executablePath:process.env.NE_CHROMIUM||undefined,args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const {page,errors}=await login(browser,'Admin',admin);
  if(!outage){
   // 1-3: open a switch, see the amber port, follow its LLDP peer to the highlighted remote port.
   await page.goto(`${url}/zabbix.php?action=host.dashboard.view&hostid=${hosts['sw-core-01']}`);
   const panel=page.locator('.dashboard-widget-neportpanel');await panel.locator('.ne-port').first().waitFor({timeout:60000});
   const amber=panel.locator('.ne-port.ne-state-speed_observation',{hasText:'Gi1/0/23'});assert.equal(await amber.count(),1);step('sw-core-01 Gi1/0/23 is amber (below expected speed)');
   await amber.click();const drawer=panel.locator('.ne-drawer');assert.ok((await drawer.innerText()).includes('negotiable')||(await drawer.innerText()).includes('policy'));
   await drawer.getByRole('link',{name:'sw-access-17'}).click();
   const remote=page.locator('.dashboard-widget-neportpanel');await remote.locator('.ne-port[aria-pressed="true"]').waitFor({timeout:60000});
   assert.ok((await remote.locator('.ne-port[aria-pressed="true"]').innerText()).includes('Gi1/0/48'));
   assert.ok((await remote.locator('.ne-drawer').innerText()).includes('Navigated from Gi1/0/23'));step('Peer navigation highlights sw-access-17 Gi1/0/48');
   // 4: management subnet.
   await page.goto(`${url}/zabbix.php?action=dashboard.view&dashboardid=${fleet}`);
   const topo=page.locator('.dashboard-widget-netopology');await topo.locator('svg .ne-node').first().waitFor({timeout:60000});
   assert.equal(await topo.locator('svg .ne-node').count(),5);
   assert.equal(await topo.locator('svg .ne-node-warning').getAttribute('aria-label').then(l=>l.startsWith('sw-dist-01')),true);step('10.101.0.0/16 flags sw-dist-01 and keeps it visible');
   // 5: VLAN 49 journey.
   await topo.getByRole('combobox',{name:'Overlay'}).selectOption('vlan');await topo.getByRole('combobox',{name:'VLAN',exact:true}).selectOption('49');
   await topo.getByRole('combobox',{name:'Trace VLAN from'}).selectOption(hosts['sw-access-17']);
   assert.ok((await topo.innerText()).includes('VLAN 49 stops at sw-core-01 port Gi1/0/23'));assert.equal(await topo.locator('svg .ne-edge-trace-stop').count(),1);step('VLAN 49 stops at sw-core-01 Gi1/0/23');
   // 6: STP.
   await topo.getByRole('combobox',{name:'Overlay'}).selectOption('stp');
   assert.ok((await topo.locator('svg .ne-node-root').getAttribute('aria-label')).startsWith('sw-dist-02'));
   assert.equal(await topo.locator('svg .ne-edge-stp-blocked').count(),1);assert.equal(await topo.locator('svg .ne-stp-block-mark').count(),1);step('STP: root sw-dist-02, one blocking port');
   // 7: LAG.
   await topo.getByRole('combobox',{name:'Overlay'}).selectOption('physical');
   assert.equal(await topo.locator('svg .ne-edge').count(),5);assert.ok((await topo.locator('svg').textContent()).includes('LAG ×2'));
   await topo.getByRole('button',{name:'Expand LAG member links'}).click();assert.equal(await topo.locator('svg .ne-edge').count(),6);step('Po1/Po10 is one logical link with two members');
   // 8: a stack shows its members as tabs, with ports placed by ENTITY-MIB.
   await page.goto(`${url}/zabbix.php?action=host.dashboard.view&hostid=${hosts['sw-stack-01']}`);
   const stack=page.locator('.dashboard-widget-neportpanel');await stack.locator('.ne-port').first().waitFor({timeout:60000});
   assert.deepEqual(await stack.getByRole('tab').allInnerTexts(),['Member 1','Member 2']);
   assert.deepEqual(await stack.locator('.ne-port-member h4').allInnerTexts(),['Member 1 · slot 0','Member 1 · slot 1']);
   await stack.getByRole('tab',{name:'Member 2'}).click();assert.ok((await stack.locator('.ne-port').first().innerText()).includes('Gi2/0/1'));
   await stack.getByRole('combobox',{name:'Physical layout'}).selectOption('mixed');
   assert.ok((await stack.innerText()).includes('Member 2 · slot 1 · SFP+'));step('sw-stack-01 shows two member tabs; SFP+ cages grouped apart');
   assert.deepEqual(errors,[]);
   // 9: permissions.
   const restricted=await login(browser,viewer.username,viewer.password);
   await restricted.page.goto(`${url}/zabbix.php?action=dashboard.view&dashboardid=${fleet}`);
   const rtopo=restricted.page.locator('.dashboard-widget-netopology');await rtopo.locator('svg .ne-node').first().waitFor({timeout:60000});
   assert.equal(await rtopo.locator('svg .ne-node').count(),4);
   const html=await restricted.page.content();for(const secret of HIDDEN)assert.ok(!html.includes(secret),'page leaks '+secret);
   for(const format of ['json','csv'])for(const report of ['inventory','peers','findings','stp']){
    const body=await (await restricted.page.request.get(`${url}/zabbix.php?action=networkexplorer.export&report=${report}&format=${format}`)).text();
    for(const secret of HIDDEN)assert.ok(!body.includes(secret),`${report}.${format} leaks ${secret}`);
   }
   const viewerToken=await api('user.login',{username:viewer.username,password:viewer.password});
   assert.ok(!(await api('host.get',{output:['host']},viewerToken)).some(h=>h.host==='sw-dist-01'));
   assert.deepEqual(restricted.errors,[]);step('Restricted viewer: sw-dist-01 absent from page, API, JSON and CSV');
  }
  else{
   // 10: a stopped agent.
   await page.goto(`${url}/zabbix.php?action=dashboard.view&dashboardid=${fleet}`);
   const topo=page.locator('.dashboard-widget-netopology');await topo.locator('svg .ne-node').first().waitFor({timeout:60000});
   assert.ok((await topo.locator('svg .ne-node-unreachable').getAttribute('aria-label')).includes('SNMP unreachable'));
   assert.ok((await page.locator('.dashboard-widget-nefindings').innerText()).includes('snmp_unreachable'));
   assert.deepEqual(errors,[]);step('Stopped agent: sw-access-17 shown as SNMP unreachable');
  }
  await page.screenshot({path:path.join(state,outage?'acceptance-outage.png':'acceptance.png'),fullPage:true});
  console.log(`Zabbix ${version}: ${steps.length} acceptance steps passed.`);
 }
 finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exit(1);});
