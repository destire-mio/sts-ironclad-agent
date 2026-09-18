#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "constants/SaveFileMappings.h"
#include "sim/search/GameAction.h"
#include <fstream>
#include <iostream>

using namespace sts;
using json = nlohmann::json;

json neow(const json &q) {
    GameContext g(CharacterClass::IRONCLAD, q.at("seed").get<int>(), 20);
    auto option = g.info.neowRewards[q.at("option").get<int>()];
    search::GameAction(q.at("option").get<int>()).execute(g);
    if (option.r == Neow::Bonus::TRANSFORM_TWO_CARDS && !q.value("snapshot_only", false)) {
        for (int n = 0; n < 2; ++n) {
            int selected = -1;
            for (int i = 0; i < g.info.toSelectCards.size(); ++i) {
                if (g.info.toSelectCards[i].card.id == CardId::STRIKE_RED) { selected = i; break; }
            }
            if (selected < 0) throw std::runtime_error("Strike not offered for transform");
            search::GameAction(selected).execute(g);
        }
    }
    json deck = json::array();
    for (auto c : g.deck.cards) deck.push_back({{"id", c.id}, {"upgrades", c.getUpgraded()}});
    std::sort(deck.begin(), deck.end());
    json result = {{"hp", g.curHp}, {"max_hp", g.maxHp}, {"gold", g.gold}, {"deck", deck},
                   {"card_rng", g.cardRng.counter}, {"neow_rng", g.neowRng.counter}};
    if (q.value("capture_offers", false)) {
        result["offers"] = json::array();
        if (g.screenState == ScreenState::REWARDS) {
            for (int i = 0; i < g.info.rewardsContainer.cardRewardCount; ++i) {
                json cards = json::array();
                for (auto c : g.info.rewardsContainer.cardRewards[i]) cards.push_back({{"id", c.id}, {"upgrades", c.getUpgraded()}});
                result["offers"].push_back(cards);
            }
        }
    }
    return result;
}

json battle(const json &q) {
    const std::string name = q.at("name");
    GameContext g(CharacterClass::IRONCLAD, 123, 20);
    g.curHp = 40; g.maxHp = 80; g.floorNum = 6; g.curRoom = Room::MONSTER;
    auto encounter = MonsterEncounter::CULTIST;
    if (name == "panto_event" || name == "panto_boss") {
        g.curRoom = name == "panto_event" ? Room::EVENT : Room::BOSS;
        g.obtainRelic(RelicId::PANTOGRAPH);
        encounter = MonsterEncounter::THE_GUARDIAN;
    } else if (name == "panto_hallway") {
        g.obtainRelic(RelicId::PANTOGRAPH);
    } else if (name == "mutagen_clock" || name == "clock_mutagen") {
        g.obtainRelic(name == "mutagen_clock" ? RelicId::MUTAGENIC_STRENGTH : RelicId::CLOCKWORK_SOUVENIR);
        g.obtainRelic(name == "mutagen_clock" ? RelicId::CLOCKWORK_SOUVENIR : RelicId::MUTAGENIC_STRENGTH);
    } else throw std::runtime_error("Unknown battle fixture");
    if (name == "panto_event") {
        g.act = 3; g.floorNum = 45; g.miscRng = Random(0); g.curEvent = Event::MINDBLOOM;
        g.screenState = ScreenState::EVENT_SCREEN; g.setupEvent(); g.chooseEventOption(0);
        encounter = g.info.encounter;
    }
    BattleContext b; b.init(g, encounter); auto &p = b.player;
    return {{"hp", p.curHp}, {"max_hp", p.maxHp}, {"strength", p.getStatus<PlayerStatus::STRENGTH>()},
            {"artifact", p.getStatus<PlayerStatus::ARTIFACT>()}, {"lose_strength", p.getStatus<PlayerStatus::LOSE_STRENGTH>()}};
}

int main(int argc, char **argv) {
    try {
        if (std::string(argv[1]) == "--capture") {
            std::cout << neow({{"seed", std::stoi(argv[2])}, {"option", std::stoi(argv[3])}, {"snapshot_only", true}, {"capture_offers", true}}) << '\n';
            return 0;
        }
        json cases; std::ifstream(argv[1]) >> cases;
        int passed = 0, total = 0;
        for (auto q : cases) {
            if (q.at("kind") != argv[2]) continue;
            auto actual = q.at("kind") == "neow" ? neow(q) : battle(q);
            auto expected = q.at("expected");
            if (expected.contains("deck")) std::sort(expected["deck"].begin(), expected["deck"].end());
            ++total;
            if (actual == expected) ++passed;
            else std::cerr << q.at("name") << " expected=" << expected << " actual=" << actual << '\n';
        }
        std::cout << passed << '/' << total << " original fixtures passed\n";
        return total > 0 && passed == total ? 0 : 1;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
