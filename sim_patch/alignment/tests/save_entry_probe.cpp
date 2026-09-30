#include "combat/BattleContext.h"
#include "constants/SaveFileMappings.h"
#include "game/GameContext.h"
#include "game/SaveFile.h"
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
         {"relicRng", &g.relicRng}, {"cardRng", &g.cardRng}, {"merchantRng", &g.merchantRng}})
        out["rng"][p.first] = rng(*p.second);
    if (b) {
        out["turn"] = b->turn + 1;
        out["energy"] = b->player.energy;
        out["block"] = b->player.block;
        out["powers"] = {{"Strength", b->player.getStatus<PlayerStatus::STRENGTH>()},
            {"Dexterity", b->player.getStatus<PlayerStatus::DEXTERITY>()},
            {"Weakened", b->player.getStatus<PlayerStatus::WEAK>()},
            {"Vulnerable", b->player.getStatus<PlayerStatus::VULNERABLE>()},
            {"Frail", b->player.getStatus<PlayerStatus::FRAIL>()},
            {"Artifact", b->player.getStatus<PlayerStatus::ARTIFACT>()},
            {"Metallicize", b->player.getStatus<PlayerStatus::METALLICIZE>()},
            {"Plated Armor", b->player.getStatus<PlayerStatus::PLATED_ARMOR>()}};
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

// Loading the captured save is the sole initial input; no post-load state is imported.
int main(int argc, char **argv) {
    try {
        if (argc != 2) throw std::runtime_error("one input file required");
        json q; std::ifstream(argv[1]) >> q;
        SaveFile saved(q.at("save").dump(), CharacterClass::IRONCLAD);
        GameContext g; g.initFromSave(saved);
        if (g.screenState != ScreenState::BATTLE) throw std::runtime_error("save did not resume in combat");
        auto b = std::make_unique<BattleContext>(); b->init(g);
        json result = {{"loaded_game_context",snapshot(g,nullptr)}, {"views",json::array({snapshot(g,b.get())})}};
        for (const auto &value : q.at("commands")) {
            std::istringstream line(value.get<std::string>());
            std::string kind; int index = 0, target = 0; line >> kind >> index >> target;
            if (!b) throw std::runtime_error("combat action outside battle");
            if (kind != "play" && kind != "end") throw std::runtime_error("unsupported combat command");
            search::Action a = kind == "end" ? search::Action(search::ActionType::END_TURN)
                : search::Action(search::ActionType::CARD, index-1, target);
            if (!a.isValidAction(*b)) throw std::runtime_error("illegal captured command: " + value.get<std::string>());
            a.execute(*b);
            if (b->outcome != Outcome::UNDECIDED) { b->exitBattle(g); b.reset(); }
            result["views"].push_back(snapshot(g,b.get()));
        }
        std::cout << result.dump() << '\n';
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
