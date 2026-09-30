#include "game/GameContext.h"
#include "sim/search/GameAction.h"
#include <iostream>
#include <stdexcept>

using namespace sts;
using GA=search::GameAction;
using RT=GA::RewardsActionType;
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
static GameContext game(){
    GameContext g(CharacterClass::IRONCLAD,5,20);
    g.act=1;g.floorNum=6;g.gold=1000;g.curRoom=Room::SHOP;g.screenState=ScreenState::SHOP_ROOM;
    g.regainControlAction=[](GameContext &next){next.screenState=ScreenState::MAP_SCREEN;};
    g.deck=Deck();g.deck.obtainRaw(CardId::BASH);g.deck.obtainRaw(CardId::WHIRLWIND);g.deck.obtainRaw(CardId::DEFEND_RED);
    for(auto &price:g.info.shop.prices)price=-1;
    g.info.shop.relics[0]=RelicId::BOTTLED_FLAME;g.info.shop.relicPrice(0)=275;g.info.shop.removeCost=75;
    return g;
}
static void pending(GameContext &g){CardReward r;r.push_back(CardId::SHRUG_IT_OFF);g.info.rewardsContainer.addCardReward(r);}
static void bottle(GameContext &g){
    GA(RT::RELIC,0).execute(g);check(g.screenState==ScreenState::CARD_SELECT,"bottle grid missing");GA(0).execute(g);
}
int main(int argc,char **argv){
 try{
    const std::string name=argc>1?argv[1]:"";auto g=game();
    if(name=="pending_card"){
        pending(g);bottle(g);check(g.screenState==ScreenState::REWARDS,"grid lost unclaimed card rewards");
        const auto size=g.deck.size();GA(RT::CARD,0,0).execute(g);check(g.deck.size()==size+1,"reopened card reward was not obtainable");
        GA(RT::SKIP).execute(g);check(g.screenState==ScreenState::SHOP_ROOM,"rewards lost return to shop");
        GA(RT::SKIP).execute(g);check(g.screenState==ScreenState::MAP_SCREEN,"return replaced shop exit");
    }else if(name=="pending_potion"){
        g.info.rewardsContainer.addPotion(Potion::FIRE_POTION);bottle(g);
        check(g.screenState==ScreenState::REWARDS&&g.info.rewardsContainer.potionCount==1,"grid lost potion reward");
    }else if(name=="empty_control"){
        bottle(g);check(g.screenState==ScreenState::SHOP_ROOM,"empty grid returned to rewards");
    }else if(name=="screenless_control"){
        pending(g);g.info.shop.relics[0]=RelicId::MANGO;GA(RT::RELIC,0).execute(g);
        check(g.screenState==ScreenState::SHOP_ROOM,"screenless purchase reopened rewards");
    }else if(name=="purge"||name=="cancel_purge"){
        pending(g);const auto size=g.deck.size();GA(RT::CARD_REMOVE).execute(g);
        if(name=="purge")GA(0).execute(g);else g.cancelCardSelect();
        check(g.screenState==ScreenState::REWARDS,"shop grid close lost pending rewards");
        check(g.deck.size()==size&&g.gold==1000,"shop purge settled before shop resumed");
        GA(RT::SKIP).execute(g);check(g.screenState==ScreenState::SHOP_ROOM,"purge rewards lost shop return");
        check(g.deck.size()==size-(name=="purge"),"purge/cancel changed wrong deck size");
        check(g.gold==(name=="purge"?925:1000),"purge/cancel charged wrong amount");
    }else if(name=="new_room"){
        pending(g);g.curMapNodeX=0;g.curMapNodeY=0;g.map->getNode(0,0).room=Room::REST;g.enterMapRoom();
        check(g.info.rewardsContainer.getTotalCount()==0,"previous room rewards leaked into next room");
        check(g.screenState==ScreenState::REST_ROOM,"room transition changed destination");
    }else if(name=="copy"){
        pending(g);GA(RT::RELIC,0).execute(g);auto child=g;GA(0).execute(child);
        check(g.screenState==ScreenState::CARD_SELECT&&g.info.rewardsContainer.cardRewardCount==1,"child changed parent");
        check(child.screenState==ScreenState::REWARDS,"copy lost reward continuation");
        GA(RT::CARD,0,0).execute(child);GA(RT::SKIP).execute(child);GA(RT::SKIP).execute(child);
        check(child.screenState==ScreenState::MAP_SCREEN&&g.screenState==ScreenState::CARD_SELECT,"copied continuation mutated parent");
    }else throw std::runtime_error("unknown shop rewards test");
    std::cout<<name<<" passed\n";
 }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
