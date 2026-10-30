const assert=require('node:assert/strict');const path=require('node:path');const {JSDOM}=require('jsdom');const esbuild=require('esbuild');
async function waitFor(fn){for(let n=0;n<150;n++){if(fn())return;await new Promise(r=>setTimeout(r,10));}throw Error('UI did not settle');}
(async()=>{
 const output=esbuild.buildSync({entryPoints:[path.join(__dirname,'fixtures/completion_ui.jsx')],bundle:true,platform:'browser',write:false,define:{'process.env.NODE_ENV':'"production"'}});
 const dom=new JSDOM('<div id="preview"></div>',{url:'https://tracker.test',runScripts:'dangerously',pretendToBeVisual:true});
 try{
 const w=dom.window;w.localStorage.setItem('review-last-weapon','Han 86');w.eval(output.outputFiles[0].text);
 const buttons=()=>[...w.document.querySelectorAll('button')];const button=text=>buttons().find(b=>b.textContent===text);
 const input=(label,value)=>{const el=w.document.querySelector(`[aria-label="${label}"]`);Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype,'value').set.call(el,value);el.dispatchEvent(new w.Event('input',{bubbles:true}));};
 await waitFor(()=>w.document.querySelector('[aria-label="Search weapons"]'));
 assert(button('Recent: Han 86'));assert(!button('Assign Gold'));assert.equal(w.resolutions.length,0);
 button('Recent: Han 86').click();await waitFor(()=>button('Assign Gold'));assert.equal(w.resolutions.length,0);
 button('Change weapon').click();await waitFor(()=>w.document.querySelector('[aria-label="Search weapons"]'));
 input('Search weapons','M4');await waitFor(()=>w.document.querySelectorAll('[aria-label^="Choose "]').length===1);
 w.document.querySelector('[aria-label="Choose M4"]').click();await waitFor(()=>w.document.body.textContent.includes('Weapon: M4'));
 assert.equal(w.localStorage.getItem('review-last-weapon'),'M4');assert.equal(w.resolutions.length,0);
 // Quick completionist assignment needs exactly one camo click after choosing the gun.
 button('Assign Gold').click();await waitFor(()=>w.resolutions.length===1);
 assert.equal(JSON.stringify(w.resolutions[0]),JSON.stringify(['banner-1','M4','Gold']));
 await waitFor(()=>!w.document.querySelector('[aria-label="Search camos"]').disabled);
 input('Search camos','Night Ops');await waitFor(()=>button('Assign Night Ops'));
 assert(!button('Assign Gold'));button('Assign Night Ops').click();await waitFor(()=>w.resolutions.length===2);
 assert.equal(JSON.stringify(w.resolutions[1]),JSON.stringify(['banner-1','M4','Night Ops']));
 // Larger images remain accessible and never assign progress.
 button('View larger image').click();await waitFor(()=>w.document.querySelector('[role="dialog"]'));
 button('Actual size').click();await waitFor(()=>button('Fit image'));
 w.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape'}));await waitFor(()=>!w.document.querySelector('[role="dialog"]'));
 button('View larger image').click();await waitFor(()=>w.document.querySelector('[role="dialog"]'));
 button('Close image').click();await waitFor(()=>!w.document.querySelector('[role="dialog"]'));
 assert.equal(w.resolutions.length,2);
 await waitFor(()=>!button('Dismiss banner').disabled);button('Dismiss banner').click();await waitFor(()=>w.resolutions.length===3);
 assert.equal(JSON.stringify(w.resolutions[2]),JSON.stringify(['banner-1',null,null]));
 console.log('PASS: recent gun is not preselected, weapon search selects another gun, one-click camo assignment, other-camo search, enlarged viewer, and dismiss.');
 }finally{dom.window.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
