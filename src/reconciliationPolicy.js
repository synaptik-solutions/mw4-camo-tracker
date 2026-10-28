const {weapons,allCamosForWeapon}=require('./camoCatalog');
function validateExpected(events){
  if(!Array.isArray(events)||events.length>1000)throw new Error('Invalid expected-unlocks list.');
  return events.map(e=>{const w=weapons.find(w=>w.name===e.weapon);if(!w||!allCamosForWeapon(w).some(c=>c.name===e.camo))throw new Error('Choose a supported weapon and camo.');const start=Number(e.start),end=Number(e.end);if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<start)throw new Error('Expected popup times must have 0 ≤ start ≤ end.');return{weapon:w.name,camo:e.camo,start,end};});
}
function selectedReconciliation(scan,id,indices){
  if(!scan||scan.id!==id||!Array.isArray(indices))throw new Error('Scan the menu again before applying changes.');const weapon=weapons.find(w=>w.name===scan.weapon);if(!weapon)throw new Error('Unsupported weapon.');const names=new Set(allCamosForWeapon(weapon).map(c=>c.name));return [...new Set(indices)].filter(i=>Number.isInteger(i)&&i>=0&&i<scan.rows.length).map(i=>scan.rows[i].name).filter(name=>names.has(name));
}
module.exports={validateExpected,selectedReconciliation};
