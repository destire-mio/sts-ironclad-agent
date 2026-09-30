#include "reward_observation.h"
#include "shop-presentation-json.h"
#include <functional>

static json state(const GameContext &g) {
    auto out=snapshot(g);
    out["math"]=json::array({g.mathUtilRng.seed0,g.mathUtilRng.seed1,g.mathUtilRng.counter});
    out["collections_seed48"]=g.endTurnShuffle.sharedRng.rawSeed();
    out["collections_initialized"]=g.endTurnShuffle.sharedRngInitialized;
    out["presentation"]=shopPresentationToJson(g.shopPresentation,&g.endTurnShuffle.sharedRng);
    out["prices"]=g.info.shop.prices;
    out["stock"]={{"relics",g.info.shop.relics},{"potions",g.info.shop.potions},{"cards",json::array()}};
    for(const auto &c:g.info.shop.cards) out["stock"]["cards"].push_back(card(c));
    out["remove_cost"]=g.info.shop.removeCost;
    return out;
}
static void rejected(GameContext g,const std::function<void(GameContext &)> &action) {
    const auto before=state(g);bool threw=false;
    try {action(g);} catch(const std::invalid_argument &) {threw=true;}
    if(!threw || before!=state(g)) throw std::runtime_error("unsupported action changed game or RNG");
}
int main(int argc,char **argv) {
    try {
        if(argc!=2) throw std::runtime_error("one presentation input required");
        json q;std::ifstream(argv[1])>>q;
        GameContext g(CharacterClass::IRONCLAD,5,20);
        g.screenState=ScreenState::SHOP_ROOM;g.curRoom=Room::SHOP;g.curHp=40;g.maxHp=80;g.gold=1000;
        g.potions[0]=Potion::BLOOD_POTION;g.potionCount=1;
        g.info.shop=Shop{};
        for(auto &price:g.info.shop.prices) price=-1;
        g.info.shop.relics[0]=RelicId::VAJRA;g.info.shop.relicPrice(0)=132;
        g.info.shop.potions[0]=Potion::FIRE_POTION;g.info.shop.potionPrice(0)=44;
        g.info.shop.removeCost=75;
        auto unprofiled=g;
        const bool upgrade=q.at("initial_presentation").at("profile")=="installed-shop-v6";
        const bool obtain=upgrade || q.at("initial_presentation").at("profile")=="installed-shop-v5";
        const bool rewards=obtain || q.at("initial_presentation").at("profile")=="installed-shop-v4";
        if (rewards) for (const auto &p:q.at("spec").at("stock").at("potions")) {
            const int slot=p.at("slot");g.info.shop.potions[slot]=shopPresentationPotion(p.at("id"));g.info.shop.potionPrice(slot)=p.at("price");
        }
        g.attachShopPresentation(shopPresentationFromJson(q.at("initial_presentation")),12345,67890);
        if (upgrade) {
            for (const auto relic:{RelicId::WHETSTONE,RelicId::WAR_PAINT}) {
                auto wrongProfile=g;wrongProfile.info.shop.relics[0]=relic;wrongProfile.shopPresentation.trackUpgrade=false;
                rejected(wrongProfile,[](auto &s){GA(RT::RELIC,0).execute(s);});
                for (int clock:{-1,0,1,241}) {
                    auto incomplete=g;incomplete.info.shop.relics[0]=relic;incomplete.shopPresentation.timing.upgrade=clock;
                    rejected(incomplete,[](auto &s){GA(RT::RELIC,0).execute(s);});
                }
            }
            rejected(g,[&q](auto &s){s.attachShopPresentation(shopPresentationFromJson(q.at("initial_presentation")),7,9);});
            std::cout<<"upgrade guards preserved game and both RNG states\n";
            return 0;
        }
        if (obtain) {
            for (const auto relic:{RelicId::LEES_WAFFLE,RelicId::MANGO,RelicId::DOLLYS_MIRROR}) {
                auto incomplete=g;incomplete.info.shop.relics[0]=relic;incomplete.shopPresentation.trackObtain=false;
                rejected(incomplete,[](auto &s){GA(RT::RELIC,0).execute(s);});
            }
            for (int clock:{0,60,241}) {
                auto incomplete=g;incomplete.info.shop.relics[0]=RelicId::DOLLYS_MIRROR;incomplete.shopPresentation.timing.mirror=clock;
                rejected(incomplete,[](auto &s){GA(RT::RELIC,0).execute(s);});
            }
            auto noRelicClock=g;noRelicClock.info.shop.relics[0]=RelicId::LEES_WAFFLE;noRelicClock.shopPresentation.timing.relic=0;
            rejected(noRelicClock,[](auto &s){GA(RT::RELIC,0).execute(s);});
            auto child=g;child.info.shop.relics[0]=RelicId::DOLLYS_MIRROR;GA(RT::RELIC,0).execute(child);
            for (int clock:{0,60,241}) {
                auto incomplete=child;incomplete.shopPresentation.timing.mirror=clock;
                rejected(incomplete,[](auto &s){GA(0).execute(s);});
            }
            auto wrongProfile=child;wrongProfile.shopPresentation.trackObtain=false;
            rejected(wrongProfile,[](auto &s){GA(0).execute(s);});
            rejected(g,[&q](auto &s){s.attachShopPresentation(shopPresentationFromJson(q.at("initial_presentation")),7,9);});
            std::cout<<"obtain guards preserved game and both RNG states\n";
            return 0;
        }
        if (rewards) {
            for (int which=0;which<3;++which) {
                auto incomplete=g;incomplete.info.shop.relics[0]=which==2?RelicId::ORRERY:RelicId::CAULDRON;
                if (which==0) incomplete.shopPresentation.timing.rewardReturn=0;
                if (which==1) incomplete.shopPresentation.timing.rewardPotion=0;
                if (which==2) incomplete.shopPresentation.timing.rewardCard=0;
                rejected(incomplete,[](auto &s){GA(RT::RELIC,0).execute(s);});
            }
            auto child=g;child.screenState=ScreenState::REWARDS;child.shopPresentation.shopVisible=false;
            child.shopPresentation.rewardsVisible=true;child.relics.add({RelicId::SINGING_BOWL,0});
            CardReward cards;cards.push_back(CardId::STRIKE_RED);child.info.rewardsContainer.addCardReward(cards);
            child.info.rewardsContainer.addPotion(Potion::FIRE_POTION);
            child.shopPresentation.rewardPotions.push_back({Potion::FIRE_POTION,0});
            child.regainControlAction=[](auto &s){s.screenState=ScreenState::SHOP_ROOM;};
            for (int which=0;which<5;++which) {
                auto incomplete=child;
                if (which==0) incomplete.shopPresentation.timing.rewardCard=0;
                if (which==1) incomplete.shopPresentation.timing.rewardBowl=0;
                if (which==2) incomplete.shopPresentation.timing.rewardPotion=0;
                if (which==3) incomplete.shopPresentation.timing.rewardPeek=0;
                if (which==4) incomplete.shopPresentation.timing.rewardReturn=0;
                rejected(incomplete,[which](auto &s){
                    if (which==0) GA(RT::CARD,0,0).execute(s);
                    if (which==1) GA(RT::CARD,0,5).execute(s);
                    if (which==2) GA(RT::POTION,0).execute(s);
                    if (which==3) s.shopPresentation.peekReward(s.mathUtilRng);
                    if (which==4) GA(RT::SKIP).execute(s);
                });
            }
            rejected(g,[&q](auto &s){s.attachShopPresentation(shopPresentationFromJson(q.at("initial_presentation")),7,9);});
            auto shortPurge=g;shortPurge.info.rewardsContainer.addCardReward(cards);
            shortPurge.regainControlAction=[](auto &s){s.screenState=ScreenState::MAP_SCREEN;};
            shortPurge.info.shop.buyCardRemove(shortPurge);shortPurge.shopPresentation.timing.purgeConfirm=4;
            rejected(shortPurge,[](auto &s){GA(0).execute(s);});
            std::cout<<"reward guards preserved game and both RNG states\n";
            return 0;
        }
        if (g.shopPresentation.trackPurge) {
            for (int which=0;which<3;++which) {
                auto incomplete=g;
                if (which==0) incomplete.shopPresentation.timing.purgeOpen=0;
                if (which==1) incomplete.shopPresentation.timing.purgeConfirm=0;
                if (which==2) incomplete.shopPresentation.timing.purgeCancel=0;
                rejected(incomplete,[](auto &s){GA(RT::CARD_REMOVE).execute(s);});
            }
            std::cout<<"three incomplete purge clocks preserved game and RNG\n";
            return 0;
        }
        rejected(g,[](auto &s){GA(0x80000000U).execute(s);});
        rejected(g,[](auto &s){s.drinkPotionAtIdx(0);});
        rejected(g,[](auto &s){GA(RT::RELIC,0).execute(s);});
        rejected(g,[](auto &s){GA(RT::CARD_REMOVE).execute(s);});
        auto noPotion=g;noPotion.shopPresentation.timing.potion=0;
        rejected(noPotion,[](auto &s){GA(RT::POTION,0).execute(s);});
        auto noDiscard=g;noDiscard.shopPresentation.timing.discard=0;
        rejected(noDiscard,[](auto &s){GA(0xc0000000U).execute(s);});
        auto noGrid=g;noGrid.info.shop.relics[0]=RelicId::BOTTLED_FLAME;noGrid.shopPresentation.timing.grid=0;
        rejected(noGrid,[](auto &s){GA(RT::RELIC,0).execute(s);});
        GA(0x80000000U).execute(unprofiled);
        if(unprofiled.curHp!=56 || unprofiled.potionCount!=0 || unprofiled.potions[0]!=Potion::EMPTY_POTION_SLOT)
            throw std::runtime_error("legacy potion control changed");
        std::cout<<"seven rejected operations preserved game and RNG; unprofiled blood potion healed 16\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
