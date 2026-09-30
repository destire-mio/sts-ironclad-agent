#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "sim/search/BattleScumSearcher2.h"
#include <iostream>
#include <stdexcept>
#include <vector>
#include <string>
using namespace sts;
using S=search::BattleScumSearcher2;
using R=RelicId;
static int checks=0;
static void check(bool x,const char *why){++checks;if(!x)throw std::runtime_error(why);}
struct Case {const char *name;int hp,maxHp,expectedHp,expectedMax;std::vector<R> relics;};
static GameContext game(const std::vector<R>& relics){
 GameContext g(CharacterClass::IRONCLAD,123,20);g.relics=RelicContainer{};
 for(auto r:relics)g.relics.add({r,-1});
 g.regainControlAction=[](GameContext&){};return g;
}
static bool same(const Random&a,const Random&b){return a.seed0==b.seed0&&a.seed1==b.seed1&&a.counter==b.counter;}
int main(){
 std::vector<Case> cases={
  {"bone39",39,80,51,80,{R::MEAT_ON_THE_BONE}},
  {"bone40_boundary",40,80,52,80,{R::MEAT_ON_THE_BONE}},
  {"bone41",41,80,41,80,{R::MEAT_ON_THE_BONE}},
  {"bone_odd_low",37,75,49,75,{R::MEAT_ON_THE_BONE}},
  {"bone_odd_high",38,75,38,75,{R::MEAT_ON_THE_BONE}},
  {"bone_small_cap",4,8,8,8,{R::MEAT_ON_THE_BONE}},
  {"burning",39,80,45,80,{R::BURNING_BLOOD}},
  {"burning_cap",78,80,80,80,{R::BURNING_BLOOD}},
  {"black_blood",39,80,51,80,{R::BLACK_BLOOD}},
  {"bone_before_blood",39,80,57,80,{R::BURNING_BLOOD,R::MEAT_ON_THE_BONE}},
  {"bone_black",39,80,63,80,{R::BLACK_BLOOD,R::MEAT_ON_THE_BONE}},
  {"flower_bone_blood",39,80,66,80,{R::BURNING_BLOOD,R::MAGIC_FLOWER,R::MEAT_ON_THE_BONE}},
  {"flower_black",39,80,57,80,{R::BLACK_BLOOD,R::MAGIC_FLOWER}},
  {"bloom_bone_blood",39,80,39,80,{R::BURNING_BLOOD,R::MEAT_ON_THE_BONE,R::MARK_OF_THE_BLOOM}},
  {"bloom_flower",39,80,39,80,{R::BLACK_BLOOD,R::MEAT_ON_THE_BONE,R::MAGIC_FLOWER,R::MARK_OF_THE_BLOOM}},
  {"cleric_full",80,80,81,81,{R::FACE_OF_CLERIC}},
  {"cleric_flower",79,80,81,81,{R::FACE_OF_CLERIC,R::MAGIC_FLOWER}},
  {"cleric_blocked",80,80,80,81,{R::FACE_OF_CLERIC,R::MARK_OF_THE_BLOOM}},
  {"bone_before_cleric_threshold",38,75,39,76,{R::FACE_OF_CLERIC,R::MEAT_ON_THE_BONE}},
  {"cleric_blood",76,80,81,81,{R::FACE_OF_CLERIC,R::BURNING_BLOOD}},
  {"blood_cleric",76,80,81,81,{R::BURNING_BLOOD,R::FACE_OF_CLERIC}},
  {"no_hp_effects",39,80,39,80,{R::BLACK_STAR,R::BLOODY_IDOL}},
  {"zero_no_resurrection",0,80,0,80,{R::BURNING_BLOOD,R::MEAT_ON_THE_BONE}},
  // Preserve even artificial zero-HP victory fixture ordering in the real exit.
  {"zero_cleric_first",0,80,7,81,{R::FACE_OF_CLERIC,R::BURNING_BLOOD}},
  {"zero_cleric_last",0,80,1,81,{R::BURNING_BLOOD,R::FACE_OF_CLERIC}}
 };
 for(const auto& c:cases){
  auto g=game(c.relics);BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.player.curHp=c.hp;b.player.maxHp=c.maxHp;b.potionCount=0;b.turn=0;b.outcome=Outcome::PLAYER_VICTORY;
  auto before=b;const auto sum=BattleContext::sum;const auto projected=b.victoryHpRelics.project(c.hp,c.maxHp);
  check(projected.curHp==c.expectedHp&&projected.maxHp==c.expectedMax,c.name);
  check(S::evaluateEndState4q(b)==100*(35+c.hp),"legacy score changed");
  for(int j=0;j<3;++j)check(S::evaluateEndState4r(b,c.maxHp)==100*(35+c.expectedHp),c.name);
  check(b.player.curHp==c.hp&&b.player.maxHp==c.maxHp&&BattleContext::sum==sum,"projection mutated HP/global state");
  check(same(b.aiRng,before.aiRng)&&same(b.cardRandomRng,before.cardRandomRng)&&same(b.miscRng,before.miscRng)&&same(b.monsterHpRng,before.monsterHpRng)&&same(b.potionRng,before.potionRng)&&same(b.shuffleRng,before.shuffleRng),"projection consumed RNG");
  b.exitBattle(g);check(g.curHp==c.expectedHp&&g.maxHp==c.expectedMax,"real exit differs");
  std::cout<<"{\"case\":\""<<c.name<<"\",\"raw_hp\":"<<c.hp<<",\"post_hp\":"<<g.curHp<<",\"max_hp\":"<<g.maxHp<<"}\n";
 }
 auto g=game({R::MEAT_ON_THE_BONE});BattleContext a;a.init(g,MonsterEncounter::CULTIST);a.player.curHp=39;a.player.maxHp=80;a.potionCount=0;a.turn=0;a.outcome=Outcome::PLAYER_VICTORY;auto b=a;b.player.curHp=41;
 check(S::evaluateEndState4q(a)<S::evaluateEndState4q(b),"counterexample old order");
 check(S::evaluateEndState4r(a,80)>S::evaluateEndState4r(b,80),"counterexample new order");
 auto child=a;child.victoryHpRelics.healingBlocked=true;check(S::evaluateEndState4r(child,80)==7400&&S::evaluateEndState4r(a,80)==8600,"profile copy isolation");
 a.player.curHp=41;a.player.maxHp=83;check(S::evaluateEndState4r(a,80)==9100,"Feed and victory HP interaction");
 for(auto outcome:{Outcome::PLAYER_LOSS,Outcome::PLAYER_ESCAPE,Outcome::UNDECIDED}){a.outcome=outcome;check(S::evaluateEndState4r(a,80)==S::evaluateEndState4q(a),"non-victory score changed");}
 a.outcome=Outcome::PLAYER_ESCAPE;a.player.curHp=39;a.player.maxHp=80;a.exitBattle(g);check(g.curHp==51,"escape settlement changed");
 a.outcome=Outcome::PLAYER_LOSS;a.player.curHp=0;a.exitBattle(g);check(g.curHp==0,"death settlement healed");
 auto cap=game({R::BURNING_BLOOD});a.init(cap,MonsterEncounter::CULTIST);a.player.maxHp=80;a.player.curHp=78;a.potionCount=0;a.turn=0;a.outcome=Outcome::PLAYER_VICTORY;b=a;b.player.curHp=79;
 check(S::evaluateEndState4r(a,80)==S::evaluateEndState4r(b,80),"capped healing tie");
 // A retained shop presentation profile is synthetic at battle end, but its
 // existing real-heal callback must not disappear when factoring HP rules.
 auto effects=game({R::MEAT_ON_THE_BONE,R::BURNING_BLOOD,R::MAGIC_FLOWER});
 effects.curHp=39;effects.maxHp=80;effects.shopPresentation.configured=true;
 effects.shopPresentation.trackRewards=true;auto expectedEffects=effects;
 BattleContext effectBattle;effectBattle.init(effects,MonsterEncounter::CULTIST);
 effectBattle.outcome=Outcome::PLAYER_VICTORY;
 expectedEffects.playerHeal(18);expectedEffects.playerHeal(9);
 auto rngBefore=effects.mathUtilRng;
 check(effectBattle.victoryHpRelics.project(39,80).curHp==66&&same(effects.mathUtilRng,rngBefore),"projection emitted healing effects");
 effectBattle.updateRelicsOnExit(effects);
 check(effects.curHp==66&&same(effects.mathUtilRng,expectedEffects.mathUtilRng),"real healing callback RNG lost");
 check(effects.shopPresentation.pendingHealLines.size()==expectedEffects.shopPresentation.pendingHealLines.size()&&effects.shopPresentation.pendingHealNumbers.size()==expectedEffects.shopPresentation.pendingHealNumbers.size(),"real healing presentation lost");
 check(!same(effects.mathUtilRng,rngBefore),"callback fixture did not advance RNG");
 std::cout<<"{\"cases\":"<<cases.size()<<",\"checks\":"<<checks<<",\"counterexample_order_reversed\":true}\n";
}
