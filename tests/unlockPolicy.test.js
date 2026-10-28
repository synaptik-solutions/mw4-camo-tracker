const assert = require('node:assert/strict');
const { isSupportedUnlock } = require('../src/unlockPolicy');
const { weapons, allCamosForWeapon } = require('../src/camoCatalog');
for (const weapon of weapons) {
  for (const camo of allCamosForWeapon(weapon)) {
    assert(isSupportedUnlock({weapon:weapon.name,camo:camo.name}), `${weapon.name}: ${camo.name}`);
  }
  assert(isSupportedUnlock({weapon:weapon.name,family:'MILITARY CAMO',number:8}));
  for (const number of [0,9,55,null]) assert(!isSupportedUnlock({weapon:weapon.name,family:'MILITARY CAMO',number}));
  for (const camo of ['HULHIARY','WEAPON LEVEL','ATTACHMENT','NEW UNLOCK','RANK UP']) {
    assert(!isSupportedUnlock({weapon:weapon.name,camo}));
  }
}
assert(!isSupportedUnlock({weapon:'UNKNOWN',camo:'GOLD'}));
assert(!isSupportedUnlock({weapon:'NOT A GUN',family:'MILITARY CAMO',number:1}));
console.log('PASS: supported camos across all 33 weapons accepted; unrelated banners and invalid unlocks rejected.');
