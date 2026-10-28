const { weapons, allCamosForWeapon } = require('./camoCatalog');
const key = value => String(value || '').trim().toUpperCase();
const byAlias = new Map();
for (const weapon of weapons) {
  for (const alias of [weapon.name, ...(weapon.aliases || [])]) byAlias.set(key(alias), weapon);
}

function isSupportedUnlock(event) {
  const weapon = byAlias.get(key(event.weapon));
  if (!weapon) return false;
  if (event.camo) return allCamosForWeapon(weapon).some(c => key(c.name) === key(event.camo));
  const limits = { 'MILITARY CAMO':weapon.militaryLevels.length, 'SPECIAL CAMO':weapon.specials.length,
    'COMPLETIONIST CAMO':weapon.completionist.length };
  return Number.isInteger(event.number) && event.number > 0 && event.number <= (limits[key(event.family)] || 0);
}
function canonicalUnlock(event) {
  const weapon=byAlias.get(key(event.weapon));
  if(!weapon||!isSupportedUnlock(event))return null;
  const family=key(event.family);
  const list=family==='SPECIAL CAMO'?weapon.specials:family==='COMPLETIONIST CAMO'?weapon.completionist:null;
  return list?{...event,camo:key(list[event.number-1].name),family:null,number:null}:event;
}
module.exports = { isSupportedUnlock,canonicalUnlock };
