const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {createHash}=require('node:crypto');
const hash=content=>createHash('sha256').update(content).digest('hex');
const runtime=require('../../frontend/neportpanel/assets/js/runtime.js');
test('physical port state uses explicit intended speed, independent of maximum capability',()=>{
 assert.equal(runtime.portState({admin_status:'up',oper_status:'up',speed_bps:1e9,max_speed_bps:1e10}),'up');
 assert.equal(runtime.portState({admin_status:1,oper_status:1,speed_bps:1e9,expected_speed_bps:1e10}),'degraded');
 assert.equal(runtime.portState({admin_status:2,oper_status:2}),'disabled');
 assert.equal(runtime.portState({admin_status:'up',oper_status:'down'}),'down');
 assert.equal(runtime.portState({}),'unknown');
 assert.equal(runtime.speed(1e9),'1 Gb/s');
});
test('ports retain stack member and slot geometry with natural port order',()=>{
 const ports=[{name:'Eth10',member:1,slot:0,port:10},{name:'Eth2',member:1,slot:0,port:2},{name:'Eth1',member:2,slot:0,port:1}];
 const groups=runtime.groupPorts(ports,'stack');
 assert.equal(groups.length,2);assert.deepEqual(groups[0].ports.map(p=>p.port),[2,10]);assert.equal(groups[1].ports[0].member,2);
 assert.equal(runtime.isPhysical({type:'ethernetCsmacd'}),false);
 assert.equal(runtime.isPhysical({physical:true}),true);
});
test('300-node deterministic layout preserves supplied previous positions',()=>{
 const hosts=Array.from({length:310},(_,i)=>({hostid:String(i+1),name:'Switch '+(i+1)}));
 const edges=[{source:'1',target:'2'},{source:'2',target:'3'}];
 const first=runtime.graphLayout(hosts,edges);assert.equal(first.length,300);assert.deepEqual(first,runtime.graphLayout(hosts,edges));
 assert.equal(new Set(first.map(h=>`${h.x},${h.y}`)).size,300);
 const second=runtime.graphLayout(hosts,edges,new Map([['1',{x:777,y:888}]]));assert.equal(second.find(h=>h.hostid==='1').x,777);
});
test('LAG grouping retains parallel members and independent links',()=>{
 const edges=[{id:'a',source:'1',target:'2',lag_id:'L1'},{id:'b',source:'1',target:'2',lag_id:'L1'},{id:'c',source:'1',target:'2'},{id:'d',source:'1',target:'3',lag_id:'L1'}];
 const grouped=runtime.groupedEdges(edges);assert.equal(grouped.length,3);assert.equal(grouped[0].members.length,2);assert.equal(runtime.groupedEdges(edges,false).length,4);
});
test('peer navigation permits core relative routes and validates highlight context',()=>{
 const url=runtime.peerUrl('zabbix.php?action=host.dashboard.view&hostid=12',{hostid:'12',uid:'name:Gi1/0/1'},'Switch 1');
 assert.equal(runtime.fragmentContext('#'+url.split('#')[1]).uid,'name:Gi1/0/1');
 for(const bad of ['javascript:alert(1)','https://attacker.invalid/zabbix.php?action=host.dashboard.view','//attacker.invalid/zabbix.php?action=host.dashboard.view','zabbix.php?action=user.delete'])assert.equal(runtime.safeNavigation(bad),null);
 assert.equal(runtime.fragmentContext('#ne='+encodeURIComponent(JSON.stringify({hostid:'12',uid:'x\n'}))),null);
});
test('VLAN roles, link carry and trace follow the spec categories',()=>{
 const trunk={vlan:{mode:'trunk',pvid:1,carried:'1,10-12',untagged:'1',forbidden:'99'}};
 assert.equal(runtime.vlanRole(trunk,11),'tagged');assert.equal(runtime.vlanRole(trunk,1),'native');
 assert.equal(runtime.vlanRole(trunk,99),'not_permitted');assert.equal(runtime.vlanRole(trunk,20),'not_permitted');
 assert.equal(runtime.vlanRole({vlan:{mode:'access',carried:'49',untagged:'49'}},49),'access');
 assert.equal(runtime.vlanRole({vlan:{mode:'access',carried:'49',untagged:'49'}},10),'unrelated');
 assert.equal(runtime.vlanRole({},10),'unknown');
 assert.deepEqual([...runtime.vlanSet('1,4093-4096,x')],[1,4093,4094]);
 const edges=[{id:'ab',source:'a',target:'b',vlan:{common:'10',source_only:'',target_only:''}},
  {id:'bc',source:'b',target:'c',vlan:{common:'',source_only:'10',target_only:''}},{id:'cd',source:'c',target:'d',vlan:{common:'10'}}];
 assert.equal(runtime.edgeVlanState(edges[0],10),'carried');assert.equal(runtime.edgeVlanState(edges[1],10),'stopped');
 assert.equal(runtime.edgeVlanState(edges[1],20),'unrelated');assert.equal(runtime.edgeVlanState({},10),'unknown');
 const trace=runtime.vlanTrace({edges},'a',10);assert.deepEqual(trace.reached,['a','b']);assert.equal(trace.stops.length,1);
 assert.equal(trace.stops[0].hostid,'c');assert.equal(runtime.stpClass({state:'discarding'}),'blocking');assert.equal(runtime.stpClass(null),'unknown');
});
test('LAG member links group by the reader\'s lag_ids into one logical link',()=>{
 const edges=[{id:'m1',source:'11',target:'13',lag_ids:['lag-b','lag-a']},{id:'m2',source:'11',target:'13',lag_ids:['lag-a','lag-b']},{id:'x',source:'11',target:'14',lag_ids:[]}];
 const grouped=runtime.groupedEdges(edges);assert.equal(grouped.length,2);assert.equal(grouped.find(g=>g.id==='m1').members.length,2);
});
test('CSV exports escape quotes and spreadsheet formulas',()=>{
 const csv=runtime.findingsCsv([{hostid:'1',title:'=HYPERLINK("bad")',rule:'speed',severity:'warning',reason:'comma, "quoted"'}],{hosts:[{hostid:'1',name:'Switch'}]});
 assert.ok(csv.includes('"\'=HYPERLINK(""bad"")"'));assert.ok(csv.includes('"comma, ""quoted"""'));assert.ok(csv.startsWith('\ufeff'));
 for(const prefix of [' ','  ','\t','\r','\n',' \t','\ufeff']){const title=prefix+'=HYPERLINK("bad")';const output=runtime.findingsCsv([{title}],{});assert.ok(output.includes('"\''+prefix+'=HYPERLINK(""bad"")"'),'CSV formula escaped after whitespace '+JSON.stringify(prefix));}
});
test('widget manifests use only native host/item broadcasts and identical pinned local runtime',()=>{
 const ids=['neportpanel','netopology','neinterfacedetail','nedataquality','nefindings'];
 const expected=fs.readFileSync(path.join(__dirname,'../../frontend/neportpanel/assets/js/runtime.js'));
 for(const id of ids){const directory=path.join(__dirname,'../../frontend',id);const manifest=JSON.parse(fs.readFileSync(path.join(directory,'manifest.json')));assert.equal(manifest.id,id);assert.equal(manifest.widget.in.override_hostid.type,'_hostid');assert.ok(manifest.widget.out.every(o=>['_hostid','_itemid'].includes(o.type)));assert.equal(hash(fs.readFileSync(path.join(directory,'assets/js/runtime.js'))),hash(expected),id+' runtime must match');}
});
