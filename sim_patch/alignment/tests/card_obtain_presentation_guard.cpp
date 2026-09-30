#include "reward_observation.h"
#include "shop-presentation-json.h"
#include <functional>

static json state(const GameContext &g) {
    auto out=snapshot(g);
    out["math"]=json::array({g.mathUtilRng.seed0,g.mathUtilRng.seed1,g.mathUtilRng.counter});
    out["collections"]=json::array({g.endTurnShuffle.sharedRng.rawSeed(),g.endTurnShuffle.sharedRngInitialized});
    out["presentation"]=shopPresentationToJson(g.shopPresentation,&g.endTurnShuffle.sharedRng);
    out["prices"]=g.info.shop.prices;
    return out;
}
static void rejected(GameContext g,const json &input) {
    const auto before=state(g);bool threw=false;
    try {g.attachShopPresentation(shopPresentationFromJson(input),7,9);}
    catch(const std::invalid_argument &) {threw=true;}
    if(!threw || before!=state(g)) throw std::runtime_error("rejected obtain scope changed game or RNG");
}
int main(int argc,char **argv) {
    try {
        if(argc!=2) throw std::runtime_error("one original presentation input required");
        json q;std::ifstream(argv[1])>>q;
        GameContext g(CharacterClass::IRONCLAD,5,20);
        g.screenState=ScreenState::SHOP_ROOM;g.curRoom=Room::SHOP;
        g.info.shop=Shop{};
        for(auto &price:g.info.shop.prices) price=-1;
        for(const auto &p:q.at("spec").at("stock").at("potions")) {
            const int slot=p.at("slot");g.info.shop.potions[slot]=shopPresentationPotion(p.at("id"));g.info.shop.potionPrice(slot)=p.at("price");
        }
        for(int charge:{-1,3}) {
            auto child=g;child.relics.add({RelicId::OMAMORI,charge});
            rejected(child,q.at("initial_presentation"));
        }
        auto child=g;child.relics.add({RelicId::CERAMIC_FISH,-1});
        auto wrong=q.at("initial_presentation");wrong["profile"]="installed-shop-v4";
        wrong["action_frames"].erase("MIRROR");wrong["action_frames"].erase("UPGRADE");
        rejected(child,wrong);
        std::cout<<"three obtain scope rejections preserved game and both RNG states\n";
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
