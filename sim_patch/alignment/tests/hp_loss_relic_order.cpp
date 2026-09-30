#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include <iostream>
#include <stdexcept>
using namespace sts;
static void check(bool okay,const char *why) {if(!okay) throw std::runtime_error(why);}
static void settle(BattleContext &b) {b.setState(InputState::EXECUTING_ACTIONS);b.executeActions();}
static BattleContext fixture(bool cubeFirst) {
    GameContext g(CharacterClass::IRONCLAD,123,20);g.curHp=40;
    g.relics.add({cubeFirst?R::RUNIC_CUBE:R::CENTENNIAL_PUZZLE,-1});
    g.relics.add({cubeFirst?R::CENTENNIAL_PUZZLE:R::RUNIC_CUBE,-1});
    g.relics.add({R::SUNDIAL,2});
    BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();
    b.player.energy=0;b.player.block=0;
    b.monsters.arr[0].curHp=b.monsters.arr[0].maxHp=300;
    for(auto id:{CardId::BASH,CardId::VOID}) b.cards.drawPile.emplace_back(id);
    for(auto id:{CardId::STRIKE_RED,CardId::DEFEND_RED,CardId::ARMAMENTS,CardId::ANGER}) b.cards.discardPile.emplace_back(id);
    return b;
}
int main() {
    try {
        for(bool cubeFirst:{true,false}) {
            auto b=fixture(cubeFirst);b.player.loseHp(b,2,true);auto child=b;
            settle(b);
            check(b.player.energy==(cubeFirst?1:2) && b.cards.cardsInHand==4,"run initialization lost HP-loss relic order");
            check(child.player.energy==0 && child.cards.cardsInHand==0,"queued draw execution changed sibling");
            child.player.energy=1;settle(child);
            check(child.player.energy==2 && b.player.energy==(cubeFirst?1:2),"queued draw captured another battle");
            b.cards=CardManager();for(int i=0;i<3;++i)b.cards.drawPile.emplace_back(CardId::STRIKE_RED);
            b.player.loseHp(b,2,true);settle(b);
            check(b.cards.cardsInHand==1,"second HP loss reused Centennial Puzzle");
        }
        auto b=fixture(true);auto child=b;
        child.player.setHasRelic<R::RUNIC_CUBE>(false);child.player.setHasRelic<R::RUNIC_CUBE>(true);
        b.player.loseHp(b,2,true);child.player.loseHp(child,2,true);settle(b);settle(child);
        check(b.player.energy==1 && child.player.energy==2,"relic mutation lost order or changed sibling");
        b=fixture(true);b.player.setHasRelic<R::RUNIC_CUBE>(true);b.player.loseHp(b,2,true);settle(b);
        check(b.cards.cardsInHand==4 && b.player.energy==1,"relic refresh duplicated or reordered draws");
        b=fixture(true);b.player.setHasRelic<R::TUNGSTEN_ROD>(true);b.player.loseHp(b,1,true);settle(b);
        check(b.cards.cardsInHand==0 && b.player.hasRelic<R::CENTENNIAL_PUZZLE>(),"zero HP loss consumed draw relics");
        b=fixture(true);b.player.debuff<PS::NO_DRAW>(1,false);b.player.loseHp(b,2,true);settle(b);
        check(b.cards.cardsInHand==0 && !b.player.hasRelic<R::CENTENNIAL_PUZZLE>(),"No Draw changed Puzzle consumption");
        std::cout<<"run initialization, callback order, repeated loss, queued copy, relic mutation and damage controls passed\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
