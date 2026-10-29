const assert=require('node:assert/strict');const path=require('node:path');const {JSDOM}=require('jsdom');const esbuild=require('esbuild');
async function waitFor(fn){for(let n=0;n<150;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('UI did not settle');}
(async()=>{
 const output=esbuild.buildSync({entryPoints:[path.join(__dirname,'fixtures/completion_ui.jsx')],bundle:true,platform:'browser',write:false,define:{'process.env.NODE_ENV':'"production"'}});
 const dom=new JSDOM('<div id="preview"></div>',{runScripts:'dangerously',pretendToBeVisual:true});
 try{
 const w=dom.window;w.eval(output.outputFiles[0].text);await waitFor(()=>w.document.querySelector('select'));
 const buttons=()=>[...w.document.querySelectorAll('button')];const assign=()=>buttons().find(b=>b.textContent==='Assign camo');
 assert(assign().disabled);assert.equal(w.resolutions.length,0);
 const weapon=w.document.querySelector('[aria-label="Banner weapon"]');weapon.value='M4';weapon.dispatchEvent(new w.Event('change',{bubbles:true}));
 await waitFor(()=>!w.document.querySelector('[aria-label="Banner camo"]').disabled);
 const camo=w.document.querySelector('[aria-label="Banner camo"]');camo.value='Gold';camo.dispatchEvent(new w.Event('change',{bubbles:true}));
 await waitFor(()=>!assign().disabled);assign().click();await waitFor(()=>w.resolutions.length===1);
 assert.equal(JSON.stringify(w.resolutions[0]),JSON.stringify(['banner-1','M4','Gold']));
 await waitFor(()=>!buttons().find(b=>b.textContent==='Dismiss').disabled);buttons().find(b=>b.textContent==='Dismiss').click();
 await waitFor(()=>w.resolutions.length===2);assert.equal(JSON.stringify(w.resolutions[1]),JSON.stringify(['banner-1',null,null]));
 console.log('PASS: completion review starts empty, explicit weapon/camo required, dismiss does not assign.');
 }finally{dom.window.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
