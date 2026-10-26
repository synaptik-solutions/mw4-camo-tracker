const CLASS_COMPLETIONIST = {
  'Assault Rifles': { platinum: 'Get 50 headshot kills against Players', harmonic: 'Get 25 Double Kills against Players' },
  'SMGs': { platinum: 'Get 25 kills from behind against Players', harmonic: 'Get 50 hipfire kills against Players' },
  'Shotguns': { platinum: 'Get 125 hipfire kills against Players', harmonic: 'Get 2 kills without reloading 25 times against Players' },
  'LMGs': { platinum: 'Get 3 kills without dying 15 times against Players', harmonic: 'Get 2 kills without releasing the trigger 25 times against Players' },
  'Marksman Rifles': { platinum: 'Get 75 kills while prone against Players', harmonic: 'Get 75 one-shot kills against Players' },
  'Sniper Rifles': { platinum: 'Get 75 kills while prone against Players', harmonic: 'Get 75 one-shot kills against Players' },
  'Pistols': { platinum: 'Get 20 kills from behind against Players', harmonic: 'Get 40 hipfire kills against Players' },
  'Launchers': { platinum: 'Get 2 kills without taking damage 15 times against Players', harmonic: 'Get 10 kills in a match 7 times against Players' },
  'Melee': { platinum: 'Get 3 kills without dying 15 times against Players', harmonic: 'Get 25 kills from behind against Players' }
};

const pending = 'Verify exact Multiplayer requirement in-game';

const weapon = (name, category, militaryLevels, specials, aliases = []) => ({
  name, category, militaryLevels, specials, aliases,
  completionist: [
    { name: 'Gold', requirement: 'Complete all 8 Military and all 3 Special camos, then get 15 Player kills in a single match' },
    { name: 'Platinum', requirement: CLASS_COMPLETIONIST[category].platinum },
    { name: 'Harmonic Break', requirement: CLASS_COMPLETIONIST[category].harmonic },
    { name: 'Divergence', requirement: 'Complete Harmonic Break on 33 weapons' }
  ]
});

const weapons = [
  weapon('Axion','Assault Rifles',[10,19,26,34,41,48,55,62],[
    {name:'Splinter Rock', requirement:'Get 20 longshot kills against Players', dmz:'Get 75 longshot kills'},
    {name:'Sunset Tropic', requirement:'Get 25 kills using the Miri 40MM grenade launcher against Players', dmz:'Get 75 kills using the Miri 40MM grenade launcher'},
    {name:'Cyan', requirement:'Get 2 kills without reloading 25 times against Players', dmz:'Get 2 kills without reloading 50 times'}
  ]),
  weapon('Han 86','Assault Rifles',[10,18,25,34,42,50,57,65],[
    {name:'Smoke', requirement:'Get 20 kills while Mounted against Players', dmz:'Get 75 kills while Mounted', official:true},
    {name:'Stormwave', requirement:'Get 50 kills using a Suppressor against Players', dmz:'Get 125 kills using a Suppressor', official:true},
    {name:'Red', requirement:'Get 3 kills without dying against Players', dmz:'Get 3 kills without taking damage 50 times', official:true}
  ],['HAN 86']),
  weapon('M4','Assault Rifles',[10,18,26,35,39,44,51,59],[
    {name:'Myriad', requirement:'Get 20 point blank kills against Players', dmz:'Get 75 point blank kills'},
    {name:'Night Ops', requirement:'Get 20 kills while Mounted against Players', dmz:'Get 75 kills while Mounted'},
    {name:'Green', requirement:'Get 25 kills from behind against Players', dmz:'Get 100 kills from behind'}
  ]),
  weapon('Hyeon Burst','Assault Rifles',[10,17,26,32,40,49,55,62],[
    {name:'Ponderosa', requirement:'Get 2 kills without reloading 10 times against Players', dmz:'Get 2 kills without reloading 30 times'},
    {name:'Red Rain', requirement:'Get 20 longshot kills against Players', dmz:'Get 75 longshot kills'},
    {name:'Kitty Kaos', requirement:'Get 100 kills while using Full Auto against Players', dmz:'Get 250 kills using a Suppressor'}
  ]),
  weapon('Kastov 762','Assault Rifles',[10,19,27,37,45,54,61,67],[
    {name:'Raster Aux', requirement:pending, dmz:'Get 75 longshot kills'},
    {name:'Samnim', requirement:pending, dmz:'Get 5 kills without taking damage 25 times'},
    {name:'Yellow', requirement:pending, dmz:'Get 100 hipfire kills'}
  ]),
  weapon('Patriot XMR','Assault Rifles',[11,20,28,36,43,52,59,66],[
    {name:'Dune Sea', requirement:pending, dmz:'Get 75 hipfire kills'},
    {name:'Scorch', requirement:pending, dmz:'Get 125 kills using a Suppressor'},
    {name:'Disperse', requirement:'Get 30 longshot kills against Players', dmz:'Get 100 longshot kills'}
  ]),
  weapon('Oden','Assault Rifles',[12,21,25,33,39,46,53,59],[
    {name:'Dark Moss', requirement:'Get 25 kills using the Miri 40MM grenade launcher against Players', dmz:'Get 75 kills using the Miri 40MM grenade launcher'},
    {name:'Shale', requirement:'Get 2 kills without reloading 10 times against Players', dmz:'Get 2 kills without reloading 30 times'},
    {name:'Hot Rod', requirement:'Get 100 ADS kills against Players', dmz:'Get 250 ADS kills'}
  ]),
  weapon('Cronen Squall','Assault Rifles',[10,17,24,31,39,45,54,60],[
    {name:'Oni', requirement:'Get 20 point blank kills against Players', dmz:'Get 75 point blank kills'},
    {name:'Urban Smoke', requirement:'Get 20 kills while Mounted against Players', dmz:'Get 75 kills while Mounted'},
    {name:'Optical Reverb', requirement:'Get 3 kills without dying 15 times against Players', dmz:'Get 50 ADS kills'}
  ]),

  weapon('Wz. 55 Striga','SMGs',[12,18,23,29,36,41,47,54],[
    {name:'Stellation', requirement:'Get 50 kills using a Suppressor against Players', dmz:'Get 125 kills using a Suppressor'},
    {name:'Rattlesnake', requirement:'Get 20 kills while jumping against Players', dmz:'Get 50 kills while jumping'},
    {name:'Dark Tan', requirement:'Get 40 point blank kills against Players', dmz:'Get 100 point blank kills'}
  ],['WZ. 55 STRIGA','WZ 55 STRIGA']),
  weapon('ISO Nightshade','SMGs',[12,19,25,31,38,44,50,57],[
    {name:'Asphalt', requirement:'Get 50 ADS kills against Players', dmz:'Get 125 ADS kills'},
    {name:'Black Topo', requirement:'Get 10 Double Kills against Players', dmz:'Get 30 Double Kills'},
    {name:'Brown', requirement:'Get 3 kills without dying 15 times against Players', dmz:'Get 3 kills without taking damage 50 times'}
  ]),
  weapon('PPSH-41','SMGs',[11,17,23,31,38,44,51,57],[
    {name:'Blackwell', requirement:'Get 30 Double Kills against Players', dmz:'Get 30 Double Kills'},
    {name:'Currents', requirement:pending, dmz:'Get 250 ADS kills'},
    {name:'Iron', requirement:pending, dmz:'Get 75 longshot kills'}
  ],['PPSH 41']),
  weapon('X-58 NYX','SMGs',[9,15,20,25,29,35,42,47],[
    {name:'Sniper Veil', requirement:'Get 20 kills while moving against Players', dmz:'Get 75 kills while moving'},
    {name:'Carbonated', requirement:'Get 20 longshot kills against Players', dmz:'Get 75 longshot kills'},
    {name:'Lime', requirement:'Get 40 headshot kills against Players', dmz:'Get 100 longshot kills'}
  ],['X58 NYX']),
  weapon('VEL 46','SMGs',[9,15,22,28,33,40,47,54],[
    {name:'Ghast', requirement:pending, dmz:'Get 100 kills while prone'},
    {name:'Gunmetal', requirement:pending, dmz:'Get 75 headshot kills'},
    {name:'Jungle Shadow', requirement:pending, dmz:'Get 125 ADS kills'}
  ]),

  weapon('REZI 12','Shotguns',[11,18,26,30,38,42,47,54],[
    {name:'Struck Oil', requirement:'Get 20 point blank kills against Players', dmz:'Get 75 point blank kills'},
    {name:'Brushstroke', requirement:'Get 10 longshot kills against Players', dmz:'Get 50 longshot kills'},
    {name:'White Pine', requirement:'Get 40 kills while jumping against Players', dmz:'Get 100 kills while jumping'}
  ]),
  weapon('Warlord','Shotguns',[13,null,null,null,null,null,null,null],[
    {name:'Redshift', requirement:'Get 20 kills while moving against Players', dmz:'Get 75 kills while moving'},
    {name:'Corrupted Clay', requirement:'Get 10 Double Kills against Players', dmz:'Get 30 Double Kills'},
    {name:'Magma Ire', requirement:'Get 50 kills while prone against Players', dmz:'Get 125 kills while prone'}
  ]),

  weapon('FiNN LMG','LMGs',[12,18,24,31,37,42,48,53],[
    {name:'Desert Tactics', requirement:'Get 20 point blank kills against Players', dmz:'Get 75 point blank kills'},
    {name:'Green Tiger', requirement:'Get 2 kills without reloading 10 times against Players', dmz:'Get 2 kills without reloading 30 times'},
    {name:'Thunderhead', requirement:'Get 30 longshot kills against Players', dmz:'Get 100 longshot kills'}
  ],['FINN LMG','FINN']),
  weapon('Type 73','LMGs',[12,19,26,34,41,48,55,61],[
    {name:'Ash Pine', requirement:pending, dmz:'Get 75 kills while Mounted'},
    {name:'Foxtrail', requirement:pending, dmz:'Get 100 headshot kills'},
    {name:'Outcrop', requirement:pending, dmz:'Get 30 Double Kills'}
  ]),
  weapon('APOC-338','LMGs',[9,15,22,26,33,40,44,51],[
    {name:'Mineral', requirement:'Get 20 longshot kills against Players', dmz:'Get 75 longshot kills'},
    {name:'Phantom Flux', requirement:'Get 20 hipfire kills against Players', dmz:'Get 75 hipfire kills'},
    {name:'Tiger Swipe', requirement:'Get 100 kills while prone against Players', dmz:'Get 250 kills while prone'}
  ],['APOC 338']),

  weapon('MAR-9','Marksman Rifles',[10,19,29,38,45,52,58,69],[
    {name:'Mangrove', requirement:'Get 20 kills while Mounted against Players', dmz:'Get 75 kills while Mounted'},
    {name:'Fungal Grid', requirement:'Get 25 kills while crouched against Players', dmz:'Get 75 kills while crouched'},
    {name:'White', requirement:'Get 30 longshot kills against Players', dmz:'Get 100 longshot kills'}
  ],['MAR 9']),
  weapon('Oris 8.6','Marksman Rifles',[11,18,27,33,42,49,55,61],[
    {name:'Deep Space', requirement:pending, dmz:'Get 3 kills without taking damage 50 times'},
    {name:'Fire Topo', requirement:pending, dmz:'Get 50 Double Kills'},
    {name:'Hibiscus', requirement:pending, dmz:'Get 50 quickscope kills'}
  ]),
  weapon('Mosin-Nagant','Marksman Rifles',[10,17,25,31,38,47,55,61],[
    {name:'Fractal Snow', requirement:pending, dmz:'Get 2 kills without reloading 30 times'},
    {name:'Ice Sheer', requirement:pending, dmz:'Get 75 headshot kills'},
    {name:'Sticker Shock', requirement:pending, dmz:'Get 250 focused kills'}
  ],['MOSIN NAGANT']),

  weapon('KG-7 Vulcan','Sniper Rifles',[13,22,31,38,47,54,61,69],[
    {name:'Treeline', requirement:'Get 10 hipfire kills against Players', dmz:pending},
    {name:'Spidersilk', requirement:'Get 20 headshot kills against Players', dmz:'Get 75 focused kills'},
    {name:'Tension', requirement:'Get 2 kills without taking damage 20 times against Players', dmz:'Get 2 kills without taking damage 30 times'}
  ],['KG 7 VULCAN']),
  weapon('Signal 50','Sniper Rifles',[10,18,28,35,43,52,57,67],[
    {name:'Anaconda', requirement:'Get 2 kills within 5 seconds 10 times against Players', dmz:'Get 2 kills within 5 seconds 25 times'},
    {name:'Ripplewave', requirement:'Get 20 quickscope kills against Players', dmz:'Get 30 quickscope kills'},
    {name:'Sunburn', requirement:'Get 40 longshot kills against Players', dmz:'Get 100 one-shot kills'}
  ]),
  weapon('Astaroth .57','Sniper Rifles',[10,15,20,26,32,37,42,48],[
    {name:'Dry Brush', requirement:pending, dmz:'Get 3 kills without taking damage 25 times'},
    {name:'Backcountry', requirement:pending, dmz:'Get 75 kills while Mounted'},
    {name:'Dread Plague', requirement:pending, dmz:'Get 2 kills within 5 seconds 50 times'}
  ]),

  weapon('Sang 9mm','Pistols',[9,13,17,21,25,28,31,35],[
    {name:'Autumn', requirement:'Get 25 ADS kills against Players', dmz:'Get 75 ADS kills', official:true},
    {name:'Snakeskin', requirement:'Get 3 kills without dying 5 times against Players', dmz:'Get 3 kills without taking damage 15 times', official:true},
    {name:'Space Time', requirement:'Get 50 Akimbo kills against Players', dmz:'Get 125 Akimbo kills', official:true}
  ],['SANG 9MM']),
  weapon('Krait P68','Pistols',[10,14,18,22,25,28,32,35],[
    {name:'Off Grid', requirement:'Get 15 kills while ledge hanging against Players', dmz:'Get 50 kills while ledge hanging'},
    {name:'Urban Flamingo', requirement:'Get 15 point blank kills against Players', dmz:'Get 50 point blank kills'},
    {name:'Smokescreen', requirement:'Get 50 kills using a Suppressor against Players', dmz:'Get 125 kills using a Suppressor'}
  ]),
  weapon('.50 GS','Pistols',[10,16,22,28,32,36,40,46],[
    {name:'Frosted', requirement:pending, dmz:'Get 75 headshot kills'},
    {name:'Red Tiger', requirement:pending, dmz:'Get 75 point blank kills'},
    {name:'Splatter Ops', requirement:pending, dmz:'Get 20 Double Kills'}
  ],['50 GS']),
  weapon('Mojave .357','Pistols',[9,null,null,null,null,null,null,null],[
    {name:'Garland', requirement:pending, dmz:'Get 75 point blank kills'},
    {name:'Miami', requirement:pending, dmz:'Get 50 one-shot kills'},
    {name:'Wallpaper', requirement:pending, dmz:'Get 2 kills without reloading 20 times'}
  ]),

  weapon('PILA','Launchers',[6,11,16,21,26,31,36,41],[
    {name:'Frontier', requirement:'Get 10 direct-hit kills against Players', dmz:'Get 25 direct-hit kills'},
    {name:'Sandwash', requirement:'Get 5 Double Kills against Players', dmz:'Get 100 kills'},
    {name:'Digital Fall', requirement:'Destroy 30 enemy killstreaks or vehicles', dmz:'Destroy 50 enemy killstreaks or vehicles'}
  ]),
  weapon('RPG-8','Launchers',[6,11,16,21,26,31,36,41],[
    {name:'Bubblegum Ops', requirement:pending, dmz:'Destroy 50 enemy killstreaks or vehicles'},
    {name:'Digi Bark', requirement:pending, dmz:'Get 25 kills while prone'},
    {name:'Stone Bits', requirement:pending, dmz:'Get 25 longshot kills'}
  ],['RPG 8']),
  weapon('JOKR','Launchers',[6,11,16,21,26,31,36,41],[
    {name:'Blue Tiger', requirement:pending, dmz:'Destroy 50 enemy killstreaks or vehicles'},
    {name:'Tectonic', requirement:pending, dmz:'Get 25 longshot kills'},
    {name:'Thicket', requirement:pending, dmz:'Get 15 Double Kills'}
  ]),
  weapon('PM-40 Anvil','Launchers',[6,11,16,21,26,31,36,41],[
    {name:'Night Snow', requirement:'Get 10 direct-hit kills against Players', dmz:'Get 25 direct-hit kills'},
    {name:'Recursive', requirement:'Get 5 Double Kills against Players', dmz:'Get 2 kills without reloading 20 times'},
    {name:'Urban Standard', requirement:'Destroy 30 enemy killstreaks or vehicles', dmz:'Get 100 kills while moving'}
  ],['PM 40 ANVIL']),

  weapon('FSS Carbon Edge 1095','Melee',[6,11,16,21,26,31,36,41],[
    {name:'Raster Lite', requirement:'Get 25 kills while jumping against Players', dmz:'Get 100 kills while jumping'},
    {name:'Stockpile', requirement:'Get 25 heavy melee finisher kills against Players', dmz:'Get 75 heavy melee finisher kills'},
    {name:'Deathbed', requirement:'Get 2 kills within 5 seconds 25 times against Players', dmz:'Get 2 kills within 5 seconds 50 times'}
  ],['FSS CARBON EDGE'])
];

const mastery = [
  { name:'Mercurial Drift', requirement:'Get 10 kills in a match 250 times' },
  { name:'Polyatomic Reforged', requirement:'Get 3 kills without taking damage 300 times' },
  { name:'Orion Reforged', requirement:'Get 5 kills without dying 500 times' }
];

const prestige = [
  { name:'Pyroclast', requirement:'Reach Weapon Prestige 1, Level 1' },
  { name:'Pyroclast Terminus', requirement:'Reach the maximum level of Weapon Prestige 1' },
  { name:'Pyroclast Scatter', requirement:'Reach Prestige Master 150' },
  { name:'Pyroclast Cascade', requirement:'Reach Prestige Master 250' }
];

const categories = ['Assault Rifles','SMGs','Shotguns','LMGs','Marksman Rifles','Sniper Rifles','Pistols','Launchers','Melee'];

function allCamosForWeapon(w) {
  return [
    ...w.militaryLevels.map((level,i)=>({ name:`Military Camo ${i+1}`, type:'Military', requirement:level ? `Unlocks at Weapon Level ${level}` : 'Weapon level requirement: verify in-game' })),
    ...w.specials.map(x=>({ ...x, type:'Special' })),
    ...w.completionist.map(x=>({ ...x, type:'Completionist' }))
  ];
}

module.exports = { weapons, categories, mastery, prestige, allCamosForWeapon, pending };
