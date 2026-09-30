#include "reward_observation.h"
#include "shop-presentation-json.h"
#include <stdexcept>

static json state(const GameContext &g) {
    auto out=snapshot(g);
    out["outcome"]=static_cast<int>(g.outcome);out["screen"]=static_cast<int>(g.screenState);
    out["potion_count"]=g.potionCount;
    out["math"]=json::array({g.mathUtilRng.seed0,g.mathUtilRng.seed1,g.mathUtilRng.counter});
    out["collections"]=json::array({g.endTurnShuffle.sharedRng.rawSeed(),g.endTurnShuffle.sharedRngInitialized});
    out["presentation"]=shopPresentationToJson(g.shopPresentation,&g.endTurnShuffle.sharedRng);
    return out;
}
static void require(bool okay,const char *message) {if(!okay) throw std::runtime_error(message);}
static void rejected(GameContext g,int index) {
    const auto before=state(g);bool threw=false;
    try {g.claimPotionReward(index);} catch(const std::invalid_argument &) {threw=true;}
    require(threw && state(g)==before,"invalid reward click changed game or RNG");
}
static GameContext rewardGame() {
    GameContext g(CharacterClass::IRONCLAD,5,20);g.screenState=ScreenState::REWARDS;
    g.info.rewardsContainer=Rewards{};
    for(auto p:{Potion::FIRE_POTION,Potion::BLOCK_POTION,Potion::BLOOD_POTION}) g.info.rewardsContainer.addPotion(p);
    g.potions[0]=Potion::FIRE_POTION;g.potions[1]=Potion::BLOCK_POTION;g.potionCount=2;
    return g;
}
int main(int argc,char **argv) {
    try {
        if(argc!=2) throw std::runtime_error("one original presentation input required");
        auto g=rewardGame();auto parent=state(g);auto child=g;
        require(!GA(RT::POTION,2).isValidAction(g),"full click entered policy actions");
        require(!child.claimPotionReward(2),"full claim incorrectly removed reward");
        require(state(child)==parent && state(g)==parent,"full click or copy changed purchase state");
        child.discardPotionAtIdx(0);require(GA(RT::POTION,2).isValidAction(child),"discard did not unlock policy claim");
        require(child.claimPotionReward(2),"available claim refused");
        require(child.potions[0]==Potion::BLOOD_POTION && child.potionCount==2 && child.info.rewardsContainer.potionCount==2,"claim selected wrong reward or slot");
        require(child.info.rewardsContainer.potions[0]==Potion::FIRE_POTION && child.info.rewardsContainer.potions[1]==Potion::BLOCK_POTION,"claim reordered other rewards");
        require(state(g)==parent,"claim on child mutated parent");
        auto sozu=g;sozu.relics.add({RelicId::SOZU,-1});auto potions=sozu.potions;
        require(sozu.claimPotionReward(1) && sozu.info.rewardsContainer.potionCount==2 && sozu.potions==potions,"Sozu did not remove reward without obtaining");
        json q;std::ifstream(argv[1])>>q;auto guarded=g;
        guarded.screenState=ScreenState::SHOP_ROOM;guarded.curRoom=Room::SHOP;guarded.info.shop=Shop{};
        guarded.info.rewardsContainer=Rewards{};
        for(auto &price:guarded.info.shop.prices) price=-1;
        for(const auto &p:q.at("spec").at("stock").at("potions")) {
            int i=p.at("slot");guarded.info.shop.potions[i]=shopPresentationPotion(p.at("id"));guarded.info.shop.potionPrice(i)=p.at("price");
        }
        guarded.attachShopPresentation(shopPresentationFromJson(q.at("initial_presentation")),7,9);
        guarded.screenState=ScreenState::REWARDS;guarded.shopPresentation.rewardsVisible=true;
        guarded.info.rewardsContainer=g.info.rewardsContainer;
        for(int i=0;i<guarded.info.rewardsContainer.potionCount;++i) guarded.shopPresentation.rewardPotions.push_back({guarded.info.rewardsContainer.potions[i],0});
        rejected(guarded,-1);rejected(guarded,3);rejected(guarded,65535);
        auto v=guarded;v.screenState=ScreenState::SHOP_ROOM;rejected(v,0);
        v=guarded;v.screenState=ScreenState::MAP_SCREEN;rejected(v,0);
        v=guarded;v.outcome=GameOutcome::PLAYER_LOSS;rejected(v,0);
        v=guarded;v.outcome=GameOutcome::PLAYER_VICTORY;rejected(v,0);
        v=guarded;v.info.rewardsContainer=Rewards{};rejected(v,0);
        v=guarded;v.shopPresentation.timing.rewardPotion=0;rejected(v,0);
        std::cout<<"full reward preserved; discard then claim; Sozu removes reward; copy isolation; nine atomic rejections passed\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
