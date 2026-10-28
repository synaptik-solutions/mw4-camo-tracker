const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {WorkerJobs}=require('../src/reliabilityJobs');
const {validateExpected,selectedReconciliation}=require('../src/reconciliationPolicy');
const {captureWarnings}=require('../src/captureWarnings');
const {canonicalUnlock}=require('../src/unlockPolicy');
const {weapons}=require('../src/camoCatalog');

async function main(){
 const child=()=>Object.assign(new EventEmitter(),{stdout:new EventEmitter(),stderr:new EventEmitter(),pid:123});
 const children=[],killed=[],progress=[];
 const jobs=new WorkerJobs(()=>{const p=child();children.push(p);return p;},p=>killed.push(p.pid),p=>progress.push(p));
 const result=jobs.run('detector',['--replay','clip.mp4']);
 children[0].stdout.emit('data','{"type":"job-progress","message":"Reading"}\n{"type":"job-');
 children[0].stdout.emit('data','result","result":{"matched":1}}\n');children[0].emit('close',0);
 assert.equal((await result).result.matched,1);assert.equal(jobs.active.size,0);assert.equal(progress[0].message,'Reading');
 const cancelled=jobs.run('detector',['--scan-menu']);const rejection=assert.rejects(cancelled,/cancelled/);
 await assert.rejects(jobs.run('detector',[]),/already running/);jobs.cancelAll();await rejection;
 assert.deepEqual(killed,[123]);assert.equal(jobs.active.size,0);children[1].emit('close',1);
 const failed=jobs.run('detector',[]);children[2].stderr.emit('data','OCR failed');children[2].emit('close',1);await assert.rejects(failed,/OCR failed/);
 assert.deepEqual(validateExpected([{weapon:'M4',camo:'Gold',start:4,end:8}]),[{weapon:'M4',camo:'Gold',start:4,end:8}]);
 for(const e of [{weapon:'UNKNOWN',camo:'Gold',start:0,end:1},{weapon:'M4',camo:'fake',start:0,end:1},{weapon:'M4',camo:'Gold',start:8,end:1}])assert.throws(()=>validateExpected([e]));
 const scan={id:'scan-1',weapon:'M4',rows:[{name:'Gold'},{name:'Platinum'},{name:'fake'}]};
 assert.deepEqual(selectedReconciliation(scan,'scan-1',[0,0,2,99]),['Gold']);assert.throws(()=>selectedReconciliation(scan,'old',[0]));
 assert.deepEqual(captureWarnings({issues:[]},1,false,99999),[]);
 assert(captureWarnings({issues:[]},1,true,9000).some(x=>x.includes('heartbeat')));
 assert(captureWarnings({zones:{center:{unchangedForSec:9,blankForSec:0}}},10000,true,10001).some(x=>x.includes('may be a static menu')));
 assert(captureWarnings({zones:{center:{blankForSec:4}}},10000,true,10001).some(x=>x.includes('blank')));
 for(const w of weapons){for(const [family,rows] of [['SPECIAL CAMO',w.specials],['COMPLETIONIST CAMO',w.completionist]]){
   for(let i=0;i<rows.length;i++){const e=canonicalUnlock({weapon:w.name,family,number:i+1});assert.equal(e.camo,rows[i].name.toUpperCase());assert.equal(e.family,null);}
 }}
 console.log('PASS: job cancellation, protocol parsing, reconciliation scope, expected events, capture warnings and numeric camo mapping.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
