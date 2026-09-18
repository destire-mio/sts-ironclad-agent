"""Training proposals that value draw, mitigation, and existing Ironclad synergies.

This is a data-collection teacher, not a change to the deployed or frozen prior.
Its hand-set scores are hypotheses; paired terminal outcomes select the proposal.
"""
from collections import Counter
import heart_runtime as R

ORIGINAL_CARD_VALUE=R.card_value
ORIGINAL_CHOICE=R.heuristic_choice

ROLE_VALUES={
    'OFFERING':95,'BATTLE_TRANCE':75,'SHRUG_IT_OFF':60,'POMMEL_STRIKE':55,
    'BURNING_PACT':48,'DARK_EMBRACE':55,'FEEL_NO_PAIN':60,'TRUE_GRIT':40,
    'DISARM':75,'SHOCKWAVE':75,'IMPERVIOUS':85,'REAPER':75,'CORRUPTION':95,
    'FIEND_FIRE':80,'IMMOLATE':95,'UPPERCUT':65,'FLAME_BARRIER':55,
    'POWER_THROUGH':50,'SECOND_WIND':45,'HEADBUTT':35,'ARMAMENTS':35,
    'FLEX':5,'CLASH':0,'RAMPAGE':5,'THUNDERCLAP':20,'DUAL_WIELD':15,
    'PERFECTED_STRIKE':20,'SWORD_BOOMERANG':25,'HEAVY_BLADE':20,
    'ENTRENCH':5,'BODY_SLAM':15,'BARRICADE':30,'RUPTURE':5,'JUGGERNAUT':25,
    'INFLAME':55,'SPOT_WEAKNESS':55,'LIMIT_BREAK':25,'DEMON_FORM':55,
    'BRUTALITY':35,'EVOLVE':30,'BLOODLETTING':35,'BERSERK':30,
}
def role_card_value(gc,card):
    if card.type==R.sts.CardType.CURSE:return -100.0
    name=card.id.name
    if name not in ROLE_VALUES and name not in ('ANGER','CARNAGE','TWIN_STRIKE','CLOTHESLINE','HEMOKINESIS'):
        return ORIGINAL_CARD_VALUE(gc,card)
    counts=Counter(c.id.name for c in gc.deck)
    base=float(ROLE_VALUES.get(name,45))
    strength=sum(counts[k] for k in ('INFLAME','SPOT_WEAKNESS','DEMON_FORM','LIMIT_BREAK'))
    exhaust=sum(counts[k] for k in ('CORRUPTION','FEEL_NO_PAIN','DARK_EMBRACE','SECOND_WIND','FIEND_FIRE','BURNING_PACT','TRUE_GRIT'))
    if name in ('ANGER','CARNAGE','TWIN_STRIKE','CLOTHESLINE','HEMOKINESIS'):
        base=60.0 if gc.act==1 else 25.0
    if name=='DEMON_FORM' and gc.act==1:base=20.0
    if name in ('DARK_EMBRACE','FEEL_NO_PAIN'):base+=min(3,exhaust)*10
    if name in ('SWORD_BOOMERANG','HEAVY_BLADE','LIMIT_BREAK'):base+=min(3,strength)*18
    if name=='BODY_SLAM':base+=30*bool(counts['BARRICADE'])+15*bool(counts['ENTRENCH'])
    if name=='ENTRENCH':base+=45*bool(counts['BARRICADE'])
    if name=='BARRICADE':base+=20*bool(counts['ENTRENCH'])+10*bool(counts['IMPERVIOUS'])
    if name=='RUPTURE':base+=35*bool(counts['BRUTALITY'] or counts['COMBUST'])
    if name=='EVOLVE':base+=15*bool(counts['POWER_THROUGH'] or counts['WILD_STRIKE'] or counts['RECKLESS_CHARGE'])
    if card.upgrade_count:base+=6
    if card.type==R.sts.CardType.ATTACK and gc.act==1:
        attacks=sum(c.type==R.sts.CardType.ATTACK and not c.is_starter_strike_or_defend for c in gc.deck)
        base+=max(0,3-attacks)*9
    divisor=1+((2.0 if card.type==R.sts.CardType.POWER else 0.6)*counts[name])
    return base/divisor


class RouteView:
    def __init__(self,gc):self.gc=gc
    @property
    def green_key(self):return True
    def __getattr__(self,name):return getattr(self.gc,name)


class RoleTeacher:
    def __init__(self,green_act=1):self.green_act=green_act
    def choose(self,gc,observation,actions,descriptors):
        view=RouteView(gc) if gc.act<self.green_act and gc.screen_state==R.sts.ScreenState.MAP_SCREEN else gc
        previous=R.card_value
        try:
            R.card_value=role_card_value
            return ORIGINAL_CHOICE(view,actions,descriptors)
        finally:
            R.card_value=previous
