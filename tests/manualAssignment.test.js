const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const path = require('node:path');
const localRequire=createRequire(path.resolve(__dirname,'../src/main.js'));
let data;
class Store {
  constructor(options){data=structuredClone(options.defaults);}
  get(k){return structuredClone(data[k]);}
  set(k,v){data[k]=structuredClone(v);}
}
const ctx=vm.createContext({
  require(name){
    if(name==='electron')return {app:{getVersion:()=> 'test',whenReady:()=>({then(){}}),on(){}},ipcMain:{}};
    if(name==='electron-store')return Store;
    if(name==='electron-updater')return {autoUpdater:{}};
    return localRequire(name);
  },
  __dirname:path.resolve(__dirname,'../src'),process,console,setTimeout,clearTimeout,setImmediate,
});
vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../src/main.js'),'utf8'),ctx);
const run=code=>vm.runInContext(code,ctx);
const {weapons}=localRequire('./camoCatalog');
const weapon=weapons[0].name;
run(`saveUnlock({weapon:'UNKNOWN',family:'MILITARY CAMO',number:1,rawText:'UNLOCKED MILITARY CAMO 1',timestamp:'2026-10-28T10:00:00Z'})`);
assert.equal(data.progress.pending.length,1);
assert.deepEqual(data.progress.weapons,{});
assert.equal(data.progress.events.length,0);
run(`saveUnlock({weapon:'UNKNOWN',family:'MILITARY CAMO',number:1,timestamp:'2026-10-28T10:00:02Z'})`);
assert.equal(data.progress.pending.length,1,'Repeated samples deduplicated');
run(`saveUnlock({weapon:'UNKNOWN',family:'MILITARY CAMO',number:2,timestamp:'2026-10-28T10:00:03Z'})`);
assert.equal(data.progress.pending.length,2,'Different camo stays assignable');
const id=data.progress.pending[0].id;
assert.equal(run(`assignPending(${JSON.stringify(id)},'NOT A GUN','MILITARY CAMO 2').ok`),false);
assert.equal(data.progress.pending.length,2,'Invalid assignment retains detection');
assert.equal(run(`assignPending(${JSON.stringify(id)},${JSON.stringify(weapon)},'MILITARY CAMO 2').ok`),true);
assert.equal(data.progress.pending.length,1);
assert.deepEqual(data.progress.weapons[weapon.toUpperCase()].unlocks,['MILITARY CAMO 1','MILITARY CAMO 2']);
assert.equal(data.progress.events[0].weapon,weapon.toUpperCase());
assert.equal(data.progress.events[0].timestamp,'2026-10-28T10:00:03Z');
assert.equal(run(`assignPending(${JSON.stringify(id)},${JSON.stringify(weapon)},'MILITARY CAMO 2').ok`),false,'Cannot assign twice');
run(`dismissPending(${JSON.stringify(data.progress.pending[0].id)})`);
assert.equal(data.progress.pending.length,0);
assert.equal(data.progress.events.length,1,'Dismiss does not add progress');
run(`saveUnlock({weapon:${JSON.stringify(weapon)},family:'MILITARY CAMO',number:3})`);
assert.equal(data.progress.pending.length,0,'Valid automatic unlock remains automatic');
assert.equal(data.progress.events.length,2);
run(`saveUnlock({weapon:${JSON.stringify(weapon)},camo:'UNREADABLE CAMO',rawText:'UNLOCKED ?'})`);
assert.equal(data.progress.pending.length,1,'Unreadable title retained for correction');
assert.equal(data.progress.pending[0].rawText,'UNLOCKED ?');
console.log('PASS: unidentified detections persist, deduplicate, validate, assign/backfill, and dismiss without changing automatic tracking.');
