#include "combat/BattleContext.h"
#include "constants/SaveFileMappings.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"
#include <fstream>
#include <memory>
#include <sstream>

using namespace sts;
using json = nlohmann::json;

static json rng(const Random &r) {
    return {{"seed0", r.seed0}, {"seed1", r.seed1}, {"counter", r.counter}};
}
static json card(const CardInstance &c) {
    return {{"id", c.id}, {"upgrades", c.getUpgradeCount()}, {"cost", c.costForTurn},
            {"base_cost", c.cost}, {"free_to_play_once", c.freeToPlayOnce}};
}
static json snapshot(const GameContext &g, const BattleContext *b) {
    json out = {{"floor", g.floorNum}, {"hp", b ? b->player.curHp : g.curHp},
        {"max_hp", b ? b->player.maxHp : g.maxHp}, {"gold", b ? b->player.gold : g.gold},
        {"battle", b != nullptr}, {"rng", json::object()}};
    for (auto p : std::initializer_list<std::pair<const char*, const Random*>>{
         {"aiRng", b ? &b->aiRng : &g.aiRng}, {"monsterHpRng", b ? &b->monsterHpRng : &g.monsterHpRng},
         {"shuffleRng", b ? &b->shuffleRng : &g.shuffleRng},
         {"cardRandomRng", b ? &b->cardRandomRng : &g.cardRandomRng},
         {"miscRng", b ? &b->miscRng : &g.miscRng}, {"potionRng", b ? &b->potionRng : &g.potionRng},
         {"relicRng", &g.relicRng}, {"cardRng", &g.cardRng}})
        out["rng"][p.first] = rng(*p.second);
    if (b) {
        out["turn"] = b->turn + 1;
        out["energy"] = b->player.energy;
        out["block"] = b->player.block;
        out["strength"] = b->player.getStatus<PlayerStatus::STRENGTH>();
        for (const auto *name : {"hand", "draw_pile", "discard_pile", "exhaust_pile"})
            out[name] = json::array();
        for (int i = 0; i < b->cards.cardsInHand; ++i) out["hand"].push_back(card(b->cards.hand[i]));
        for (auto c : b->cards.drawPile) out["draw_pile"].push_back(card(c));
        for (auto c : b->cards.discardPile) out["discard_pile"].push_back(card(c));
        for (auto c : b->cards.exhaustPile) out["exhaust_pile"].push_back(card(c));
        out["monsters"] = json::array();
        for (int i = 0; i < b->monsters.monsterCount; ++i) {
            const auto &m = b->monsters.arr[i];
            out["monsters"].push_back({{"id", monsterIdStrings[static_cast<int>(m.id)]},
                {"hp", m.curHp}, {"max_hp", m.maxHp}, {"block", m.block},
                {"strength", m.getStatus<MonsterStatus::STRENGTH>()}});
        }
        out["legal_actions"] = json::array();
        for (int i = 0; i < b->cards.cardsInHand; ++i) {
            const auto &c = b->cards.hand[i];
            for (int t = 0; t < (c.requiresTarget() ? b->monsters.monsterCount : 1); ++t) {
                search::Action action(search::ActionType::CARD, i, t);
                if (action.isValidAction(*b)) out["legal_actions"].push_back("play " + std::to_string(i+1)
                    + (c.requiresTarget() ? " " + std::to_string(t) : ""));
            }
        }
        if (search::Action(search::ActionType::END_TURN).isValidAction(*b)) out["legal_actions"].push_back("end");
        std::sort(out["legal_actions"].begin(), out["legal_actions"].end());
    }
    return out;
}

int main(int argc, char **argv) {
    try {
        if (argc != 2) throw std::runtime_error("one input file required");
        json q; std::ifstream(argv[1]) >> q;
        const auto &spec = q.at("spec");
        GameContext g(CharacterClass::IRONCLAD, spec.at("seed").get<std::uint64_t>(), 20);
        g.act = 2; g.floorNum = spec.at("floor"); g.curHp = 60; g.maxHp = 80; g.gold = 1000;
        g.curRoom = Room::EVENT; g.curEvent = Event::COLOSSEUM;
        g.regainControlAction = [](GameContext &g) { g.screenState = ScreenState::MAP_SCREEN; };
        g.deck = Deck();
        for (auto entry : q.at("initial_deck")) {
            Card c(entry.at("id").get<CardId>(), entry.at("upgrades").get<int>());
            g.deck.obtainRaw(c);
            if (entry.value("bottled", false)) g.deck.bottleCard(g.deck.size()-1, CardType::ATTACK);
        }
        g.relics = RelicContainer{};
        for (auto entry : spec.at("relics"))
            g.relics.add({entry.at("id").get<RelicId>(), entry.at("counter").get<int>()});
        // Initial inputs only; no original post-action state is imported.
        const auto &initial = q.at("initial_rng");
        for (auto p : std::initializer_list<std::pair<const char*, Random*>>{
             {"aiRng", &g.aiRng}, {"monsterHpRng", &g.monsterHpRng}, {"shuffleRng", &g.shuffleRng},
             {"cardRandomRng", &g.cardRandomRng}, {"miscRng", &g.miscRng}, {"potionRng", &g.potionRng},
             {"relicRng", &g.relicRng}, {"cardRng", &g.cardRng}}) {
            p.second->seed0 = initial.at(p.first).at("seed0").get<std::uint64_t>();
            p.second->seed1 = initial.at(p.first).at("seed1").get<std::uint64_t>();
            p.second->counter = initial.at(p.first).at("counter");
        }
        const auto &pools = q.at("pools");
        g.commonRelicPool = pools.at("common").get<std::vector<RelicId>>();
        g.uncommonRelicPool = pools.at("uncommon").get<std::vector<RelicId>>();
        g.rareRelicPool = pools.at("rare").get<std::vector<RelicId>>();
        g.shopRelicPool = pools.at("shop").get<std::vector<RelicId>>();
        g.bossRelicPool = pools.at("boss").get<std::vector<RelicId>>();
        g.setupEvent(); search::GameAction(0).execute(g);
        auto b = std::make_unique<BattleContext>(); b->init(g);
        json result = json::array({snapshot(g, b.get())});
        for (const auto &value : q.at("commands")) {
            std::istringstream line(value.get<std::string>());
            std::string kind; int index = 0, target = 0; line >> kind >> index >> target;
            if (kind == "play" || kind == "end") {
                if (!b) throw std::runtime_error("combat action outside battle");
                search::Action a = kind == "end" ? search::Action(search::ActionType::END_TURN)
                    : search::Action(search::ActionType::CARD, index-1, target);
                if (!a.isValidAction(*b)) throw std::runtime_error("illegal captured command: " + value.get<std::string>());
                a.execute(*b);
                if (b->outcome != Outcome::UNDECIDED) { b->exitBattle(g); b.reset(); }
            } else if (kind == "choose") {
                if (b) throw std::runtime_error("event choice inside battle");
                search::GameAction a(index);
                if (!a.isValidAction(g)) throw std::runtime_error("illegal event choice");
                a.execute(g);
                if (g.screenState == ScreenState::BATTLE) { b = std::make_unique<BattleContext>(); b->init(g); }
            } else throw std::runtime_error("unsupported captured command");
            result.push_back(snapshot(g, b.get()));
        }
        std::cout << result.dump() << '\n';
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
