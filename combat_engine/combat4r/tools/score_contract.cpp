#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "sim/search/BattleScumSearcher2.h"
#include <stdexcept>
#include <iostream>
using namespace sts;
using S=search::BattleScumSearcher2;
static void check(bool x){if(!x)throw std::runtime_error("score contract");}
int main(){
 GameContext g(CharacterClass::IRONCLAD,123,20);g.relics=RelicContainer{};BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.player.curHp=40;b.player.maxHp=80;b.potionCount=0;b.turn=0;b.outcome=Outcome::PLAYER_VICTORY;
 check(S::evaluateEndState4q(b)==7500);check(S::evaluateEndState4r(b,80)==7500);
 b.player.maxHp=84;check(S::evaluateEndState4r(b,80)==7900);check(S::evaluateEndState4q(b)==7500);
 check(S::evaluateEndState4r(b,84)==7500);check(S::evaluateEndState4r(b,90)==7500);
 b.player.curHp++;check(S::evaluateEndState4r(b,80)==8000);b.player.curHp--;
 for(auto outcome:{Outcome::PLAYER_LOSS,Outcome::PLAYER_ESCAPE,Outcome::UNDECIDED}){b.outcome=outcome;check(S::evaluateEndState4r(b,80)==S::evaluateEndState4q(b));}
 // Fixed winning terminal pairs: Feed earns +3 capacity but costs 0/2/4 current HP.
 b.outcome=Outcome::PLAYER_VICTORY;b.player.maxHp=83;
 for(double w:{0.5,1.0,2.0})for(int hpCost:{0,2,4})std::cout<<"{\"hp_equivalent\":"<<w<<",\"hp_cost\":"<<hpCost<<",\"score_difference\":"<<100*(3*w-hpCost)<<"}\n";
}
