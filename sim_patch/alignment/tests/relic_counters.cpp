#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static GameContext game(int neow = 3) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.act=2; g.floorNum=24; g.curRoom=Room::EVENT; g.curEvent=Event::COLOSSEUM;
    g.curHp=g.maxHp=200;
    g.deck=Deck();
    for (int i=0;i<10;++i) g.deck.obtainRaw(CardId::WHIRLWIND);
    g.deck.bottleCard(0,CardType::ATTACK);
    g.relics=RelicContainer{};
    g.relics.add({RelicId::NEOWS_LAMENT,neow});
    return g;
}
static BattleContext enter(GameContext &g) {
    g.curRoom=Room::EVENT; g.setupEvent(); search::GameAction(0).execute(g);
    BattleContext b; b.init(g); return b;
}
static void end(BattleContext &b, int count=1) {
    for (int i=0;i<count;++i) {
        search::Action a(search::ActionType::END_TURN);
        check(a.isValidAction(b),"end turn is illegal"); a.execute(b);
    }
}
static void win(GameContext &g, BattleContext &b) {
    int index=-1;
    for (int i=0;i<b.cards.cardsInHand;++i) if(b.cards.hand[i].id==CardId::WHIRLWIND) {index=i;break;}
    check(index>=0,"winning Whirlwind missing");
    search::Action a(search::ActionType::CARD,index,0);
    check(a.isValidAction(b),"winning Whirlwind illegal"); a.execute(b);
    check(b.outcome==Outcome::PLAYER_VICTORY,"Whirlwind did not finish fight"); b.exitBattle(g);
}
static BattleContext second(GameContext &g) {
    search::GameAction a(1); check(a.isValidAction(g),"second fight unavailable"); a.execute(g);
    BattleContext b; b.init(g); return b;
}
static void ordinaryMonsters(const BattleContext &b) {
    for (int i=0;i<b.monsters.monsterCount;++i)
        check(b.monsters.arr[i].curHp>1,"spent Neow affected another battle");
}
int main(int argc,char **argv) {
    try {
        const std::string name=argc>1?argv[1]:"";
        if (name=="flower" || name=="flower_control" || name=="flower_restore" || name=="copy") {
            auto g=game(); g.relics.add({RelicId::HAPPY_FLOWER,name=="flower"||name=="copy"?-1:0});
            auto b=enter(g);
            if (name=="flower_restore") {
                // The public battle restoration API writes this field directly.
                b.player.happyFlowerCounter=-1; end(b);
            }
            check(b.player.happyFlowerCounter==1,"first turn did not treat restored -1 as an unstarted cycle");
            if (name=="copy") {
                auto sibling=b; auto child=g; end(sibling,2); win(child,sibling);
                check(child.relics.getRelicValue(RelicId::HAPPY_FLOWER)==0,"child did not persist completed cycle");
                check(g.relics.getRelicValue(RelicId::HAPPY_FLOWER)==-1 && b.player.happyFlowerCounter==1 && b.player.energy==3,
                      "child mutated parent battle or run counter");
            } else {
                end(b,2); check(b.player.energy==4 && b.player.happyFlowerCounter==0,"flower missed its third-turn energy");
                // Mid-battle restoration reaches turn 4, where this Slaver can
                // Entangle. The natural entry cases below cover victory/transfer.
                if (name!="flower_restore") {
                    win(g,b); check(g.relics.getRelicValue(RelicId::HAPPY_FLOWER)==0,"flower was not written back");
                    auto next=second(g); check(next.player.energy==3 && next.player.happyFlowerCounter==1,"flower shifted into next battle");
                }
            }
        } else if(name=="burner" || name=="burner_control" || name=="burner_restore") {
            auto g=game(); g.relics.add({RelicId::INCENSE_BURNER,name=="burner"?-1:0}); auto b=enter(g);
            if(name=="burner_restore") {b.player.incenseBurnerCounter=-1;end(b);}
            check(b.player.incenseBurnerCounter==1,"burner did not start restored cycle");
            end(b,5); check(b.player.getStatus<PlayerStatus::INTANGIBLE>()==1 && b.player.incenseBurnerCounter==0,"burner missed sixth-turn intangible");
            win(g,b); auto next=second(g);
            check(next.player.getStatus<PlayerStatus::INTANGIBLE>()==0 && next.player.incenseBurnerCounter==1,"burner shifted into next battle");
        } else if(name=="neow" || name=="escape" || name=="death") {
            auto g=game(1); if(name=="death")g.curHp=1;
            if(name=="escape") {g.potions[0]=Potion::SMOKE_BOMB;g.potionCount=1;}
            auto b=enter(g);
            if(name=="neow") win(g,b);
            else if(name=="escape") {
                search::Action a(search::ActionType::POTION,0,0);check(a.isValidAction(b),"Smoke Bomb illegal");a.execute(b);
                check(b.outcome==Outcome::PLAYER_ESCAPE,"Smoke Bomb did not escape");b.exitBattle(g);
            } else {end(b);check(b.outcome==Outcome::PLAYER_LOSS,"death case survived");b.exitBattle(g);}
            check(g.relics.getRelicValue(RelicId::NEOWS_LAMENT)==-2,"last Neow charge did not persist spent sentinel");
            if(name!="death")ordinaryMonsters(second(g));
        } else if(name=="inactive_control") {
            for(int count:{0,-2}) {auto g=game(count);auto b=enter(g);ordinaryMonsters(b);
                check(g.relics.getRelicValue(RelicId::NEOWS_LAMENT)==count,"initialization changed inactive sentinel");}
        } else if(name=="tea_control") {
            auto g=game();g.relics.add({RelicId::ANCIENT_TEA_SET,-1});
            g.relicsOnEnterRoom(Room::REST);g.relicsOnEnterRoom(Room::SHOP);auto b=enter(g);
            check(b.player.energy==5,"rest charge was lost on shop entry");end(b);check(b.player.energy==3,"tea repeated on next turn");
            win(g,b);check(g.relics.getRelicValue(RelicId::ANCIENT_TEA_SET)==-1,"tea remained charged after exit");
            auto next=second(g);check(next.player.energy==3,"tea repeated in next battle");
        } else throw std::runtime_error("unknown relic counter case");
        std::cout<<name<<" passed\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
