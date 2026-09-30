#include "reward_observation.h"
#include "shop-presentation-json.h"
#include <algorithm>
#include <stdexcept>

static json state(const GameContext &g) {
    auto out=snapshot(g);
    out["outcome"]=static_cast<int>(g.outcome);out["screen"]=static_cast<int>(g.screenState);
    out["potion_count"]=g.potionCount;out["prices"]=g.info.shop.prices;
    out["math"]=json::array({g.mathUtilRng.seed0,g.mathUtilRng.seed1,g.mathUtilRng.counter});
    out["collections"]=json::array({g.endTurnShuffle.sharedRng.rawSeed(),g.endTurnShuffle.sharedRngInitialized});
    out["presentation"]=shopPresentationToJson(g.shopPresentation,&g.endTurnShuffle.sharedRng);
    return out;
}
static void require(bool okay,const char *message) {if(!okay) throw std::runtime_error(message);}
static void rejected(GameContext g,GA a) {
    const auto before=state(g);bool threw=false;
    require(!a.isValidShopClick(g),"invalid click was offered");
    try {a.executeShopClick(g);} catch(const std::invalid_argument &) {threw=true;}
    require(threw && before==state(g),"rejected click mutated state or RNG");
}
static bool shopPotion(const GA &a) {return !a.isPotionAction() && a.getRewardsActionType()==RT::POTION;}
static GameContext shop() {
    GameContext g(CharacterClass::IRONCLAD,5,20);
    g.screenState=ScreenState::SHOP_ROOM;g.curRoom=Room::SHOP;g.gold=44;g.info.shop=Shop{};g.info.shop.removeCost=-1;
    for(auto &price:g.info.shop.prices) price=-1;
    g.info.shop.potions[0]=Potion::FIRE_POTION;g.info.shop.potionPrice(0)=44;
    g.info.shop.potions[1]=Potion::BLOCK_POTION;g.info.shop.potionPrice(1)=55;
    g.potions[0]=Potion::FIRE_POTION;g.potions[1]=Potion::BLOCK_POTION;g.potionCount=2;
    return g;
}
int main(int argc,char **argv) {
    try {
        if(argc!=2) throw std::runtime_error("one original presentation input required");
        auto g=shop();GA buy(RT::POTION,0);
        auto clicks=GA::getShopClicks(g),search=GA::getAllActionsInState(g);
        require(clicks.size()==2 && clicks[0].bits==buy.bits && clicks[1].getRewardsActionType()==RT::SKIP,"affordable full-slot click missing or wrong order");
        require(buy.isValidShopClick(g) && !buy.isValidAction(g),"shop click and search filters conflated");
        require(std::none_of(search.begin(),search.end(),shopPotion),"blocked click entered search");
        const auto parent=state(g);auto child=g;buy.executeShopClick(child);
        require(state(g)==parent && state(child)==parent,"unprofiled full-slot click changed purchase state");
        child.relics.add({RelicId::SOZU,-1});const auto sozu=state(child);buy.executeShopClick(child);
        require(state(child)==sozu,"Sozu click changed purchase state");
        g.discardPotionAtIdx(0);require(buy.isValidAction(g),"discard failed to unlock search purchase");
        buy.executeShopClick(g);
        require(g.gold==0 && g.potionCount==2 && g.potions[0]==Potion::FIRE_POTION && g.info.shop.potionPrice(0)==-1,"ordinary click purchase failed");
        require(state(shop())==parent,"control shop changed");
        auto ordered=shop();ordered.info.shop.removeCost=30;
        ordered.info.shop.cards[0]=Card(CardId::STRIKE_RED);ordered.info.shop.cardPrice(0)=30;
        ordered.info.shop.relics[0]=RelicId::VAJRA;ordered.info.shop.relicPrice(0)=20;
        auto order=GA::getShopClicks(ordered);
        const std::vector<RT> expected={RT::CARD_REMOVE,RT::CARD,RT::RELIC,RT::POTION,RT::SKIP};
        require(order.size()==expected.size(),"shop choices omitted or duplicated");
        for(size_t i=0;i<order.size();++i) require(order[i].getRewardsActionType()==expected[i],"shop choice ordering differs");
        json q;std::ifstream(argv[1])>>q;auto guarded=shop();
        for(const auto &p:q.at("spec").at("stock").at("potions")) {
            int i=p.at("slot");guarded.info.shop.potions[i]=shopPresentationPotion(p.at("id"));guarded.info.shop.potionPrice(i)=p.at("price");
        }
        guarded.attachShopPresentation(shopPresentationFromJson(q.at("initial_presentation")),7,9);
        auto v=guarded;v.info.shop.potionPrice(0)=-1;rejected(v,buy);
        v=guarded;v.gold=v.info.shop.potionPrice(0)-1;rejected(v,buy);
        rejected(guarded,GA(RT::POTION,3));rejected(guarded,GA(RT::POTION,65535));
        rejected(guarded,GA(RT::CARD,7));rejected(guarded,GA(0xC0000000U));
        v=guarded;v.screenState=ScreenState::MAP_SCREEN;rejected(v,buy);require(GA::getShopClicks(v).empty(),"shop clicks outside shop");
        v=guarded;v.outcome=GameOutcome::PLAYER_VICTORY;rejected(v,buy);require(GA::getShopClicks(v).empty(),"shop clicks after terminal");
        std::cout<<"shop command/search isolation; discard then purchase; choice order; eight atomic rejections passed\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
