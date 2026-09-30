#include "game/GameContext.h"
#include "sim/search/GameAction.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
using GA=search::GameAction;
using RT=GA::RewardsActionType;
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
static GameContext game(bool rewards=true){
    GameContext g(CharacterClass::IRONCLAD,5,20);
    g.act=1;g.floorNum=6;g.gold=1000;g.curHp=g.maxHp=80;
    g.curRoom=Room::SHOP;g.screenState=ScreenState::SHOP_ROOM;
    g.regainControlAction=[](GameContext &next){next.screenState=ScreenState::MAP_SCREEN;};
    g.deck=Deck();g.deck.obtainRaw(CardId::BASH);g.deck.obtainRaw(CardId::PARASITE);
    g.deck.obtainRaw(Card(CardId::STRIKE_RED,1));g.deck.obtainRaw(CardId::STRIKE_RED);
    for(auto &price:g.info.shop.prices)price=-1;
    g.info.shop.removeCost=75;g.shopRemoveCount=0;
    if(rewards){CardReward r;r.push_back(CardId::SHRUG_IT_OFF);g.info.rewardsContainer.addCardReward(r);}
    return g;
}
static void select(GameContext &g,int index){GA(RT::CARD_REMOVE).execute(g);GA(index).execute(g);}
static void pending(const GameContext &g){
    check(g.screenState==ScreenState::REWARDS,"purge did not restore rewards");
    check(g.gold==1000&&g.deck.size()==4,"purge settled before shop resumed");
    check(g.info.shop.removeCost==75&&g.shopRemoveCount==0,"purge service consumed before shop resumed");
}
static void leave(GameContext &g,int gold){
    check(g.screenState==ScreenState::SHOP_ROOM,"purge lost shop return");
    check(g.gold==gold&&g.info.shop.removeCost==-1&&g.shopRemoveCount==1,"purge payment/count differs");
    GA(RT::SKIP).execute(g);
    check(g.screenState==ScreenState::MAP_SCREEN&&g.gold==gold&&g.shopRemoveCount==1,"purge charged twice on exit");
}
int main(int argc,char **argv){
 try{
    const std::string name=argc>1?argv[1]:"";auto g=game();
    if(name=="deferred"){
        select(g,0);pending(g);GA(RT::SKIP).execute(g);
        check(g.deck.size()==3&&g.deck.cards[0].id==CardId::PARASITE,"selected card not removed on resume");leave(g,925);
    }else if(name=="parasite"){
        select(g,1);pending(g);check(g.curHp==80&&g.maxHp==80,"parasite fired before shop resumed");
        GA(RT::SKIP).execute(g);check(g.curHp==77&&g.maxHp==77,"parasite removal failed on resume");leave(g,925);
    }else if(name=="claim_before_resume"){
        g.obtainRelic(RelicId::CERAMIC_FISH);select(g,0);pending(g);
        GA(RT::CARD,0,0).execute(g);
        check(g.gold==1009&&g.deck.size()==5&&g.deck.cards[0].id==CardId::BASH,"claim saw premature purge");
        GA(RT::SKIP).execute(g);check(g.deck.size()==4&&g.deck.cards[3].id==CardId::SHRUG_IT_OFF,"purge removed the reward card");leave(g,934);
    }else if(name=="duplicate_identity"){
        select(g,2);pending(g);GA(RT::CARD,0,0).execute(g);GA(RT::SKIP).execute(g);
        check(g.deck.size()==4&&g.deck.cards[2].id==CardId::STRIKE_RED&&!g.deck.cards[2].isUpgraded(),"purge removed wrong duplicate");leave(g,925);
    }else if(name=="empty_control"){
        g=game(false);select(g,1);check(g.deck.size()==3&&g.maxHp==77,"empty shop delayed purge");leave(g,925);
    }else if(name=="cancel_control"){
        GA(RT::CARD_REMOVE).execute(g);g.cancelCardSelect();pending(g);GA(RT::CARD,0,0).execute(g);GA(RT::SKIP).execute(g);
        check(g.screenState==ScreenState::SHOP_ROOM&&g.gold==1000&&g.deck.size()==5&&g.shopRemoveCount==0,"cancel settled a purge");
        check(g.info.shop.removeCost==75&&g.maxHp==80,"cancel consumed service or parasite");
    }else if(name=="nonshop_control"){
        g=game(false);g.curRoom=Room::REST;g.openCardSelectScreen(CardSelectScreenType::REMOVE,1);GA(1).execute(g);
        check(g.screenState==ScreenState::MAP_SCREEN&&g.gold==1000&&g.deck.size()==3&&g.maxHp==77,"nonshop removal changed");
    }else if(name=="copy"){
        select(g,1);pending(g);auto child=g;GA(RT::CARD,0,0).execute(child);GA(RT::SKIP).execute(child);
        check(child.deck.size()==4&&child.maxHp==77,"copied pending purge lost selection");leave(child,925);
        pending(g);check(g.maxHp==80,"child parasite mutated parent");
        auto sibling=g;GA(RT::SKIP).execute(sibling);check(sibling.deck.size()==3&&sibling.maxHp==77,"sibling reused child state");leave(sibling,925);pending(g);
    }else throw std::runtime_error("unknown shop purge test");
    std::cout<<name<<" passed\n";
 }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
