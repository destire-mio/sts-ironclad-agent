#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
using R=RelicId;
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
static GameContext game(){
    GameContext g(CharacterClass::IRONCLAD,123,20);g.act=2;g.floorNum=24;g.curRoom=Room::EVENT;
    g.curHp=180;g.maxHp=200;g.deck=Deck();
    g.regainControlAction=[](GameContext &g){g.screenState=ScreenState::MAP_SCREEN;};
    for(int i=0;i<10;++i)g.deck.obtainRaw(CardId::WHIRLWIND);
    g.deck.obtainRaw(CardId::ASCENDERS_BANE);g.deck.bottleCard(0,CardType::ATTACK);
    g.obtainRelic(R::NEOWS_LAMENT);return g;
}
static void win(GameContext &g,BattleContext &b){
    int idx=-1;for(int i=0;i<b.cards.cardsInHand;++i)if(b.cards.hand[i].id==CardId::WHIRLWIND){idx=i;break;}
    check(idx>=0,"winning card missing");search::Action a(search::ActionType::CARD,idx,0);
    check(a.isValidAction(b),"winning card illegal");a.execute(b);
    check(b.outcome==Outcome::PLAYER_VICTORY,"fixture did not win");b.exitBattle(g);
}
int main(int argc,char **argv){
 try{
    const std::string name=argc>1?argv[1]:"";
    auto g=game();
    if(name=="starter")check(g.relics.getRelicValue(R::BURNING_BLOOD)==-1,"starter counter differs from its original constructor");
    else if(name=="passive"){
        g.obtainRelic(R::STRAWBERRY);check(g.curHp==187&&g.maxHp==207,"Strawberry lost its HP effect");
        check(g.relics.getRelicValue(R::STRAWBERRY)==-1,"passive acquisition stored a visible zero counter");
    }else if(name=="zero_controls"){
        for(auto id:{R::GIRYA,R::HAPPY_FLOWER,R::INCENSE_BURNER,R::INK_BOTTLE,R::INSERTER,R::NUNCHAKU,R::PEN_NIB,R::SUNDIAL,R::TINY_CHEST}){
            g.obtainRelic(id);check(g.relics.getRelicValue(id)==0,"explicit-zero relic inherited the inactive sentinel");
        }
    }else if(name=="positive_controls"){
        for(auto pair:std::initializer_list<std::pair<R,int>>{{R::MATRYOSHKA,2},{R::WING_BOOTS,3},{R::NLOTHS_HUNGRY_FACE,1},{R::OMAMORI,2},{R::DU_VU_DOLL,1},{R::CIRCLET,1}}){
            g.obtainRelic(pair.first);check(g.relics.getRelicValue(pair.first)==pair.second,"charge constructor changed");
        }
        g.obtainRelic(R::CIRCLET);check(g.relics.getRelicValue(R::CIRCLET)==2,"duplicate Circlet did not stack");
    }else if(name=="inactive_controls"){
        for(auto id:{R::ANCIENT_TEA_SET,R::LIZARD_TAIL,R::MAW_BANK}){g.obtainRelic(id);check(g.relics.getRelicValue(id)==-1,"inactive special counter changed");}
    }else if(name=="black_blood"){
        const auto count=g.relics.size();g.obtainRelic(R::BLACK_BLOOD);
        check(g.relics.size()==count&&!g.hasRelic(R::BURNING_BLOOD)&&g.relics.relics[0].id==R::BLACK_BLOOD,"starter replacement identity/order changed");
        check(g.relics.getRelicValue(R::BLACK_BLOOD)==-1,"Black Blood replacement has a zero counter");
    }else if(name=="bloody_idol"){
        g.obtainRelic(R::GOLDEN_IDOL);g.obtainRelic(R::OMAMORI);const auto count=g.relics.size();
        g.curEvent=Event::FORGOTTEN_ALTAR;g.setupEvent();search::GameAction a(0);check(a.isValidAction(g),"altar trade unavailable");a.execute(g);
        check(g.relics.size()==count&&!g.hasRelic(R::GOLDEN_IDOL)&&g.relics.relics[count-2].id==R::BLOODY_IDOL,"altar replacement identity/order changed");
        check(g.relics.getRelicValue(R::BLOODY_IDOL)==-1,"Bloody Idol replacement has a zero counter");
    }else if(name=="copy"){
        auto sibling=g;sibling.obtainRelic(R::STRAWBERRY);sibling.obtainRelic(R::BLACK_BLOOD);
        check(!g.hasRelic(R::STRAWBERRY)&&g.hasRelic(R::BURNING_BLOOD)&&g.curHp==180&&g.maxHp==200,"acquisition mutated sibling run");
        check(sibling.relics.getRelicValue(R::STRAWBERRY)==-1&&sibling.relics.getRelicValue(R::BLACK_BLOOD)==-1,"child counters not persistent sentinels");
    }else if(name=="transient_exit"||name=="combat_controls"){
        if(name=="transient_exit")for(auto id:{R::CAPTAINS_WHEEL,R::HORN_CLEAT,R::STONE_CALENDAR,R::KUNAI,R::SHURIKEN})g.obtainRelic(id);
        else for(auto id:{R::INK_BOTTLE,R::NUNCHAKU,R::PEN_NIB,R::GIRYA})g.obtainRelic(id);
        g.curEvent=Event::COLOSSEUM;g.setupEvent();search::GameAction(0).execute(g);BattleContext b;b.init(g);
        if(name=="transient_exit"){
            search::Action(search::ActionType::END_TURN).execute(b);check(b.player.block==14,"Horn Cleat effect changed");
            search::Action(search::ActionType::END_TURN).execute(b);check(b.player.block==18,"Captain Wheel effect changed");
            win(g,b);
            for(auto id:{R::CAPTAINS_WHEEL,R::HORN_CLEAT,R::STONE_CALENDAR,R::KUNAI,R::SHURIKEN})check(g.relics.getRelicValue(id)==-1,"temporary battle count leaked into persistent state");
        }else{
            check(b.player.getStatus<PlayerStatus::STRENGTH>()==0,"new Girya applied negative Strength");win(g,b);
            for(auto id:{R::INK_BOTTLE,R::NUNCHAKU,R::PEN_NIB})check(g.relics.getRelicValue(id)==1,"attack counter did not continue after new acquisition");
        }
    }else throw std::runtime_error("unknown relic defaults test");
    std::cout<<name<<" passed\n";
 }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
