#include "sim/search/BattleScumSearcher2.h"
#include <cmath>
#include <iostream>
#include <string>
using namespace sts;
using sts::search::BattleScumSearcher2;

int main(int argc,char**argv) {
    if(argc!=2) return 2;
    BattleContext bc;
    bc.outcome=Outcome::PLAYER_LOSS;
    bc.player.curHp=0;
    bc.turn=5;
    bc.cardsDrawn=10;
    bc.energyWasted=0;
    bc.potionCount=0;
    bc.encounter=MonsterEncounter::CHAMP;
    bc.monsters.monsterCount=bc.monsters.monstersAlive=1;
    bc.monsters.arr[0].id=MonsterId::CULTIST;
    bc.monsters.arr[0].maxHp=100;
    bc.monsters.arr[0].curHp=50;
    const std::string name(argv[1]);
    const double base=BattleScumSearcher2::evaluateEndState(bc);
    bool ok=false;
    if(name=="ordinary_failure_formula") {
        ok=std::abs(base-(5-1+10*.03+5*.2))<1e-12;
    } else if(name=="large_failure_plateau") {
        bc.cardsDrawn=1000000;
        bc.turn=100;
        const double first=BattleScumSearcher2::evaluateEndState(bc);
        bc.cardsDrawn=2000000;
        bc.turn=499;
        ok=first==24.0 && BattleScumSearcher2::evaluateEndState(bc)==first;
    } else if(name=="death_draw_invariant") {
        bc.cardsDrawn=1000000;
        ok=BattleScumSearcher2::evaluateEndState(bc)==base;
    } else if(name=="death_turn_invariant") {
        bc.turn=499;
        ok=BattleScumSearcher2::evaluateEndState(bc)==base;
    } else if(name=="death_damage_progress") {
        bc.monsters.arr[0].curHp=25;
        ok=std::abs(BattleScumSearcher2::evaluateEndState(bc)-base-2.5)<1e-12;
    } else if(name=="victory_formula") {
        bc.outcome=Outcome::PLAYER_VICTORY;
        bc.player.curHp=20;
        bc.potionCount=1;
        ok=BattleScumSearcher2::evaluateEndState(bc)==100*(35+20+4-5*.01);
    } else if(name=="victory_dominates_draw_heavy_death") {
        bc.cardsDrawn=1000000;
        const double defeat=BattleScumSearcher2::evaluateEndState(bc);
        bc.outcome=Outcome::PLAYER_VICTORY;
        bc.player.curHp=1;
        ok=BattleScumSearcher2::evaluateEndState(bc)>defeat;
    } else if(name=="unfinished_is_not_a_win") {
        bc.outcome=Outcome::UNDECIDED;
        bc.turn=500;
        bc.player.curHp=50;
        ok=BattleScumSearcher2::evaluateEndState(bc)==-1000000.0 && bc.outcome==Outcome::UNDECIDED;
    } else return 2;
    std::cout<<name<<": "<<(ok?"PASS":"FAIL")<<std::endl;
    return ok?0:1;
}
