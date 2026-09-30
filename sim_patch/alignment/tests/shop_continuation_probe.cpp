#include "reward_observation.h"
#if __has_include("shop-presentation-json.h")
#include "shop-presentation-json.h"
#define STS_SHOP_PRESENTATION 1
#endif

static bool inventoryAudit=false;
static bool sharedMathAudit=false;
static json shopSnapshot(const GameContext &g) {
    auto out=snapshot(g);const auto &s=g.info.shop;
    if (sharedMathAudit) out["math_rng"]={{"seed0",g.mathUtilRng.seed0},{"seed1",g.mathUtilRng.seed1}};
#ifdef STS_SHOP_PRESENTATION
    if (g.shopPresentation.configured) out["presentation_rng"]=shopPresentationToJson(g.shopPresentation,&g.endTurnShuffle.sharedRng);
#endif
    if (g.screenState==ScreenState::SHOP_ROOM) out["phase"]="shop";
    auto &stock=out["stock"]={{"cards",json::array()},{"relics",json::array()},
        {"potions",json::array()},{"remove_cost",s.removeCost}};
    for (int i=0;i<7;++i) if (s.cardPrice(i)>=0) {
        auto c=card(s.cards[i]);c["price"]=s.cardPrice(i);stock["cards"].push_back(c);
    }
    for (int i=0;i<3;++i) {
        if (s.relicPrice(i)>=0) stock["relics"].push_back({{"slot",i},{"id",s.relics[i]},{"price",s.relicPrice(i)}});
        if (s.potionPrice(i)>=0) stock["potions"].push_back({{"slot",i},{"id",s.potions[i]},{"price",s.potionPrice(i)}});
    }
    out["legal_relic_slots"]=json::array();
    if (g.screenState==ScreenState::SHOP_ROOM) for (int i=0;i<3;++i)
        if (GA(RT::RELIC,i).isValidShopClick(g)) out["legal_relic_slots"].push_back(i);
    if (inventoryAudit) {
        auto &actions=out["shop_actions"]=json::array();
        if (g.screenState==ScreenState::SHOP_ROOM) {
            for (const auto &a:GA::getShopClicks(g)) {
                const auto type=a.getRewardsActionType();const int slot=a.getIdx1();
                if (type==RT::CARD_REMOVE) actions.push_back({{"type","REMOVE"},{"index",0}});
                else if (type==RT::CARD) {
                    int compact=0;for (int i=0;i<slot;++i) if (s.cardPrice(i)>=0) ++compact;
                    actions.push_back({{"type","CARD"},{"index",compact}});
                } else if (type==RT::RELIC) actions.push_back({{"type","RELIC"},{"index",slot}});
                else if (type==RT::POTION) actions.push_back({{"type","POTION"},{"index",slot}});
            }
        }
    }
    return out;
}

int main(int argc,char **argv) {
    try {
        if (argc!=2) throw std::runtime_error("one input file required");
        json q;std::ifstream(argv[1])>>q;const auto &spec=q.at("spec");
        inventoryAudit=spec.value("inventory_audit",false);
        sharedMathAudit=spec.contains("math_rng");
        auto seed=spec.at("seed").get<std::uint64_t>();GameContext g(CharacterClass::IRONCLAD,seed,20);
        g.act=spec.at("act");g.floorNum=spec.at("floor");g.curHp=spec.at("hp");g.maxHp=spec.at("max_hp");g.gold=spec.at("gold");
        g.blueKey=spec.at("blue_key");g.redKey=false;g.greenKey=false;
        g.screenState=ScreenState::SHOP_ROOM;g.curRoom=Room::SHOP;
        g.regainControlAction=[](GameContext &next){next.screenState=ScreenState::MAP_SCREEN;};
        g.deck=Deck();for (auto entry:q.at("initial_deck")) {
            Card c(entry.at("id").get<CardId>(),entry.at("upgrades").get<int>());
            if (c.id==CardId::RITUAL_DAGGER) c.misc=entry.at("misc");
            g.deck.obtainRaw(c);if (entry.at("bottled").get<bool>()) g.deck.bottleCard(g.deck.size()-1,c.getType());
        }
        g.relics=RelicContainer{};for (auto entry:q.at("initial_relics"))
            g.relics.add({entry.at("id").get<RelicId>(),entry.at("counter").get<int>()});
        if (spec.contains("initial_potions")) {
            if (spec.at("initial_potions").size()!=g.potionCapacity) throw std::runtime_error("initial potion capacity differs");
            g.potionCount=0;
            for (int i=0;i<g.potionCapacity;++i) {
                g.potions[i]=spec.at("initial_potions").at(i).get<Potion>();
                if (g.potions[i]!=Potion::EMPTY_POTION_SLOT) ++g.potionCount;
            }
        }
        for (auto rng:{&g.aiRng,&g.monsterHpRng,&g.shuffleRng,&g.cardRandomRng,&g.miscRng,
            &g.potionRng,&g.relicRng,&g.cardRng,&g.merchantRng,&g.treasureRng}) *rng=Random(seed);
        if (sharedMathAudit) {
            g.mathUtilRng.seed0=spec.at("math_rng").at("seed0").get<std::int64_t>();
            g.mathUtilRng.seed1=spec.at("math_rng").at("seed1").get<std::int64_t>();g.mathUtilRng.counter=0;
            if (!g.mathUtilRng.seed0 && !g.mathUtilRng.seed1) throw std::runtime_error("invalid zero shared RNG state");
        }
        g.cardRarityFactor=5;g.potionChance=0;
        const auto &pools=q.at("pools");
        g.commonRelicPool=pools.at("common").get<std::vector<RelicId>>();
        g.uncommonRelicPool=pools.at("uncommon").get<std::vector<RelicId>>();
        g.rareRelicPool=pools.at("rare").get<std::vector<RelicId>>();
        g.shopRelicPool=pools.at("shop").get<std::vector<RelicId>>();
        g.bossRelicPool=pools.at("boss").get<std::vector<RelicId>>();
        g.colorlessCardPool=pools.at("colorless").get<std::array<CardId,35>>();
        auto &s=g.info.shop;for (auto &price:s.prices) price=-1;
        const auto &stock=spec.at("stock");s.removeCost=stock.at("remove_cost");g.shopRemoveCount=0;
        int i=0;for (auto c:stock.at("cards")) {s.cards[i]=Card(c.at("id").get<CardId>(),c.at("upgrades").get<int>());s.cardPrice(i++)=c.at("price");}
        for (auto r:stock.at("relics")) {int n=r.at("slot");s.relics[n]=r.at("id").get<RelicId>();s.relicPrice(n)=r.at("price");}
        for (auto p:stock.at("potions")) {int n=p.at("slot");s.potions[n]=p.at("id").get<Potion>();s.potionPrice(n)=p.at("price");}
        if (q.contains("initial_presentation")) {
#ifdef STS_SHOP_PRESENTATION
            g.attachShopPresentation(shopPresentationFromJson(q.at("initial_presentation")),
                g.mathUtilRng.seed0,g.mathUtilRng.seed1);
#else
            throw std::runtime_error("runtime lacks shop presentation state");
#endif
        }
        json result={{"views",json::array({shopSnapshot(g)})},{"copy_checks",json::array()}};
        for (const auto &step:q.at("steps")) {
            const std::string kind=step.at("kind");GA action;bool noop=false,blockedPotion=false;
            if (kind=="buy") {
                if (g.screenState!=ScreenState::SHOP_ROOM) throw std::runtime_error("buy outside shop");
                const auto type=step.value("type",std::string("RELIC"));RT t;
                if (type=="RELIC") t=RT::RELIC;else if (type=="CARD") t=RT::CARD;
                else if (type=="POTION") t=RT::POTION;else if (type=="REMOVE") t=RT::CARD_REMOVE;
                else throw std::runtime_error("unsupported shop purchase type");
                const int slot=step.at("slot").get<int>();
                if ((t==RT::CARD && (slot<0 || slot>=7)) ||
                    ((t==RT::POTION || t==RT::RELIC) && (slot<0 || slot>=3)) ||
                    (t==RT::CARD_REMOVE && slot!=0)) throw std::runtime_error("shop slot outside stock");
                action=GA(t,slot);blockedPotion=step.value("blocked",false);
                if (blockedPotion && t!=RT::POTION) throw std::runtime_error("blocked attempt is not a potion");
                if (blockedPotion && !(g.hasRelic(RelicId::SOZU) || g.potionCount>=g.potionCapacity))
                    throw std::runtime_error("potion attempt lacks Sozu/full-inventory condition");
                if (blockedPotion && (s.potionPrice(slot)<0 || g.gold<s.potionPrice(slot)))
                    throw std::runtime_error("potion attempt not offered by original shop");
            } else if (kind=="grid") {
                if (g.screenState!=ScreenState::CARD_SELECT) throw std::runtime_error("grid outside selection");
                action=GA(step.at("index").get<int>());
            } else if (kind=="grid_cancel") {
                if (g.screenState!=ScreenState::CARD_SELECT) throw std::runtime_error("cancel outside selection");
                action=GA(RT::SKIP);
            } else if (kind=="leave") {
                if (g.screenState!=ScreenState::SHOP_ROOM) throw std::runtime_error("leave outside shop");
                action=GA(RT::SKIP);
            } else if (kind=="discard") {
                action=GA(0xC0000000U | step.at("index").get<unsigned>());
            } else if (kind=="reward" || kind=="card_peek_skip") {
                if (g.screenState!=ScreenState::REWARDS) throw std::runtime_error("claim outside rewards");
                const std::string type=step.at("type");RT t;
                if (type=="CARD") t=RT::CARD;else if (type=="POTION") t=RT::POTION;
                else if (type=="SKIP") t=RT::SKIP;else throw std::runtime_error("unsupported shop child reward");
                action=GA(t,step.value("index",0),step.value("pick",0));noop=kind=="card_peek_skip";
            } else throw std::runtime_error("unsupported shop action");
            const bool shopClick=kind=="buy" || kind=="leave";
            const bool rewardPotionClick=kind=="reward" && step.at("type")=="POTION";
            if (!rewardPotionClick && !(shopClick?action.isValidShopClick(g):action.isValidAction(g)))
                throw std::runtime_error("illegal shop input: "+step.dump());
            auto before=shopSnapshot(g);GameContext child=g;
            // The validated core shop-click API includes blocked purchases;
            // the observer does not bypass GameAction to call a Shop guard.
            auto execute=[&](GameContext &next) {
                if (rewardPotionClick) next.claimPotionReward(step.at("index").get<int>());
                else if (shopClick) action.executeShopClick(next);
                else if (noop && next.shopPresentation.active()) next.shopPresentation.peekReward(next.mathUtilRng);
                else if (!noop) action.execute(next);
            };
            execute(child);auto after=shopSnapshot(child);
            if (shopSnapshot(g)!=before) throw std::runtime_error("shop child mutated parent");
            execute(g);
            if (shopSnapshot(g)!=after) throw std::runtime_error("shop result differs after copying");
            result["copy_checks"].push_back({{"step",result["views"].size()-1},{"parent_unchanged",true},
                {"child_matches_uncopied_branch",true},{"child_after",after}});
            result["views"].push_back(after);
        }
        std::cout<<result.dump()<<'\n';
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
