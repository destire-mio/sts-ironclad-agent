from common import *
import traceback
names='INVALID EMPTY_POTION_SLOT AMBROSIA ANCIENT_POTION ATTACK_POTION BLESSING_OF_THE_FORGE BLOCK_POTION BLOOD_POTION BOTTLED_MIRACLE COLORLESS_POTION CULTIST_POTION CUNNING_POTION DEXTERITY_POTION DISTILLED_CHAOS DUPLICATION_POTION ELIXIR_POTION ENERGY_POTION ENTROPIC_BREW ESSENCE_OF_DARKNESS ESSENCE_OF_STEEL EXPLOSIVE_POTION FAIRY_POTION FEAR_POTION FIRE_POTION FLEX_POTION FOCUS_POTION FRUIT_JUICE GAMBLERS_BREW GHOST_IN_A_JAR HEART_OF_IRON LIQUID_BRONZE LIQUID_MEMORIES POISON_POTION POTION_OF_CAPACITY POWER_POTION REGEN_POTION SKILL_POTION SMOKE_BOMB SNECKO_OIL SPEED_POTION STANCE_POTION STRENGTH_POTION SWIFT_POTION WEAK_POTION'.split()
(O/'potion-names.json').write_text(json.dumps(dict(enumerate(names)),indent=2))
rs=list(map(json.loads,gzip.open(O/'fatal-decisions.jsonl.gz','rt')))
with (O/'fatal-potion-audit.jsonl').open('x') as out:
 for r in rs:
  j=r['steps'][-1]['index'];g,rawr=restore(r['seed'],j);b=S.BattleContext();b.init(g);rec=dict(seed=r['seed'],entry=[names[int(p)] for p in b.potions],uses=[],error=None)
  try:
   for k,bit in enumerate(rawr['prefix'][j]['actions']):
    a=S.SearchAction.from_bits(bit&0xffffffff);assert a.is_valid(b)
    bef=list(b.potions);txt=str(a)
    a.execute(b);aft=list(b.potions)
    if bef!=aft:rec['uses'].append(dict(action=k,bits=bit,text=txt,before=[names[int(p)] for p in bef],after=[names[int(p)] for p in aft]))
   rec['end']=[names[int(p)] for p in b.potions];assert int(b.outcome)==2
   assert all(int(p)==1 for p in b.potions),'remaining potion'
  except Exception:rec['error']=traceback.format_exc()
  out.write(json.dumps(rec)+'\n')
