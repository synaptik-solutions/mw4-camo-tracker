const assert=require('node:assert/strict');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const esbuild=require('esbuild');
async function waitFor(predicate){for(let i=0;i<150;i++){if(predicate())return;await new Promise(r=>setTimeout(r,10));}throw new Error('UI did not settle');}
(async()=>{
 const result=esbuild.buildSync({entryPoints:[path.join(__dirname,'fixtures/reliability_ui.jsx')],bundle:true,platform:'browser',write:false,define:{'process.env.NODE_ENV':'"production"'}});
 // Only this repository's trusted test bundle runs in the virtual DOM; no URLs load.
 const dom=new JSDOM('<html><body><div id="preview"></div></body></html>',{runScripts:'dangerously',pretendToBeVisual:true});
 try{
  const {window}=dom;window.eval(result.outputFiles[0].text);
  await waitFor(()=>window.document.querySelector('h4')?.textContent==='Review M4');
  const checks=[...window.document.querySelectorAll('label.row.toggle input')];
  assert.equal(checks.length,2);assert(checks.every(input=>!input.checked));
  const weapon=[...window.document.querySelectorAll('select')].at(-1);assert.equal(weapon.value,'M4');
  checks[0].click();
  const apply=()=>[...window.document.querySelectorAll('button')].find(b=>b.textContent==='Apply selected completions');
  await waitFor(()=>!apply().disabled);apply().click();
  await waitFor(()=>window.applied);
  assert.equal(window.applied.id,'preview-scan');assert.equal(window.applied.indices.join(','),'0');
  await waitFor(()=>window.document.body.textContent.includes('Applied 1 verified camo(s).'));
  assert(!window.document.querySelector('h4'));
  console.log('PASS: Reliability controls render, restored weapon is correct, no default completions, only selected scan rows applied.');
 }finally{dom.window.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
