#include "reward_observation.h"

int main(int argc,char **argv) {
    try {
        if (argc!=2) throw std::runtime_error("one input file required");
        json q; std::ifstream(argv[1])>>q; const auto &spec=q.at("spec");
        auto seed=spec.at("seed").get<std::uint64_t>(); GameContext g(CharacterClass::IRONCLAD,seed,20);
        g.act=spec.at("act"); g.floorNum=spec.at("floor"); g.curHp=spec.at("hp");
        g.maxHp=spec.at("max_hp"); g.gold=spec.at("gold");
        g.blueKey=spec.at("blue_key"); g.redKey=false; g.greenKey=false;
        g.screenState=ScreenState::INVALID; g.curRoom=Room::TREASURE;
        g.regainControlAction=[](GameContext &next){next.screenState=ScreenState::MAP_SCREEN;};
        g.deck=Deck(); for (auto entry:q.at("initial_deck")) {
            Card c(entry.at("id").get<CardId>(),entry.at("upgrades").get<int>());
            if (c.id==CardId::RITUAL_DAGGER) c.misc=entry.at("misc");
            g.deck.obtainRaw(c); if (entry.at("bottled").get<bool>()) g.deck.bottleCard(g.deck.size()-1,c.getType());
        }
        g.relics=RelicContainer{};
        for (auto entry:q.at("initial_relics")) g.relics.add({entry.at("id").get<RelicId>(),entry.at("counter").get<int>()});
        for (auto rng : {&g.aiRng,&g.monsterHpRng,&g.shuffleRng,&g.cardRandomRng,&g.miscRng,
            &g.potionRng,&g.relicRng,&g.cardRng,&g.merchantRng,&g.treasureRng}) *rng=Random(seed);
        g.cardRarityFactor=5; g.potionChance=0;
        const auto &pools=q.at("pools");
        g.commonRelicPool=pools.at("common").get<std::vector<RelicId>>();
        g.uncommonRelicPool=pools.at("uncommon").get<std::vector<RelicId>>();
        g.rareRelicPool=pools.at("rare").get<std::vector<RelicId>>();
        g.shopRelicPool=pools.at("shop").get<std::vector<RelicId>>();
        g.bossRelicPool=pools.at("boss").get<std::vector<RelicId>>();
        json result={{"initial",snapshot(g)},{"views",json::array()},{"copy_checks",json::array()}};
        g.setupTreasureRoom(); result["views"].push_back(snapshot(g));
        for (const auto &step:q.at("steps")) {
            const std::string kind=step.at("kind"); GA action;
            if (kind=="open") {
                if (g.screenState!=ScreenState::TREASURE_ROOM) throw std::runtime_error("open outside chest");
                action=GA(0);
            } else if (kind=="grid") {
                if (g.screenState!=ScreenState::CARD_SELECT) throw std::runtime_error("selection outside grid");
                action=GA(step.at("index").get<int>());
            } else if (kind=="reward") {
                if (g.screenState!=ScreenState::REWARDS) throw std::runtime_error("claim outside rewards");
                const std::string type=step.at("type"); RT t;
                if (type=="RELIC") t=RT::RELIC; else if (type=="GOLD") t=RT::GOLD;
                else if (type=="SAPPHIRE_KEY") t=RT::KEY; else if (type=="SKIP") t=RT::SKIP;
                else throw std::runtime_error("unsupported treasure reward");
                action=GA(t,step.value("index",0));
            } else throw std::runtime_error("unsupported treasure input");
            if (!action.isValidAction(g)) throw std::runtime_error("illegal treasure input: "+step.dump());
            const auto parentBefore=snapshot(g); GameContext child=g;
            action.execute(child); const auto childAfter=snapshot(child);
            if (snapshot(g)!=parentBefore) throw std::runtime_error("treasure child mutated parent");
            action.execute(g);
            if (snapshot(g)!=childAfter) throw std::runtime_error("treasure result differs after copying");
            result["copy_checks"].push_back({{"step",result["views"].size()-1},{"parent_unchanged",true},
                {"child_matches_uncopied_branch",true},{"child_after",childAfter}});
            result["views"].push_back(snapshot(g));
        }
        std::cout<<result.dump()<<'\n';
    } catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;}
}
