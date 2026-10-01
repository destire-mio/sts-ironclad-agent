// The live bridge gives the production reuse policy an already initialized
// BattleContext. Search owns a copy; the caller advances its prediction only
// after the corresponding command has executed in the original game.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <combat_search_reuse.h>

namespace py = pybind11;
using namespace sts;
#include "live_run_state.h"

static Action queuedPower(const py::dict &a) {
    const auto owner=a["owner"].cast<std::string>();
    const auto power=a["power"].cast<std::string>();
    const int amount=a["amount"].cast<int>();
    const bool sourceMonster=a["source_monster"].cast<bool>();
    if(owner=="player") {
        if(power=="Buffer")return Actions::BuffPlayer<PS::BUFFER>(amount);
        if(power=="Intangible")return Actions::BuffPlayer<PS::INTANGIBLE>(amount);
        if(power=="Artifact")return Actions::BuffPlayer<PS::ARTIFACT>(amount);
        if(power=="Pen Nib")return Actions::BuffPlayer<PS::PEN_NIB>(amount);
        if(power=="Strength")return amount<0?Actions::DebuffPlayer<PS::STRENGTH>(amount,sourceMonster):Actions::BuffPlayer<PS::STRENGTH>(amount);
        if(power=="Dexterity")return amount<0?Actions::DebuffPlayer<PS::DEXTERITY>(amount,sourceMonster):Actions::BuffPlayer<PS::DEXTERITY>(amount);
        if(power=="LoseStrength")return Actions::DebuffPlayer<PS::LOSE_STRENGTH>(amount,sourceMonster);
        if(power=="Weak")return Actions::DebuffPlayer<PS::WEAK>(amount,sourceMonster);
        if(power=="Vulnerable")return Actions::DebuffPlayer<PS::VULNERABLE>(amount,sourceMonster);
        if(power=="Frail")return Actions::DebuffPlayer<PS::FRAIL>(amount,sourceMonster);
        if(power=="No Draw")return Actions::DebuffPlayer<PS::NO_DRAW>(amount,sourceMonster);
    } else if(owner=="monster") {
        const int target=a["target"].cast<int>();
        if(power=="Strength")return amount<0?Actions::DebuffEnemy<MS::STRENGTH>(target,amount,sourceMonster):Actions::BuffEnemy<MS::STRENGTH>(target,amount);
        if(power=="Artifact")return Actions::BuffEnemy<MS::ARTIFACT>(target,amount);
        if(power=="Weak")return Actions::DebuffEnemy<MS::WEAK>(target,amount,sourceMonster);
        if(power=="Vulnerable")return Actions::DebuffEnemy<MS::VULNERABLE>(target,amount,sourceMonster);
        if(power=="Poison")return Actions::DebuffEnemy<MS::POISON>(target,amount,sourceMonster);
    }
    throw std::invalid_argument("unsupported queued original power");
}

PYBIND11_MODULE(live_combat_search, m) {
    m.def("sync_run", &syncLiveRun);
    m.def("import_search_state", [](BattleContext &b, const py::dict &d) {
        b.cardsDrawn=d["cards_drawn"].cast<int>();
        b.energyWasted=d["energy_wasted"].cast<int>();
        b.victoryHpRelics=VictoryHpRelics{};
        for(auto id:d["relics"].cast<std::vector<int>>()) {
            auto r=static_cast<RelicId>(id);
            if(r==RelicId::MEAT_ON_THE_BONE)b.victoryHpRelics.meatOnTheBone=true;
            if(r==RelicId::MAGIC_FLOWER)b.victoryHpRelics.magicFlower=true;
            if(r==RelicId::MARK_OF_THE_BLOOM)b.victoryHpRelics.healingBlocked=true;
            if(r==RelicId::BURNING_BLOOD || r==RelicId::BLACK_BLOOD || r==RelicId::FACE_OF_CLERIC)
                b.victoryHpRelics.ordered.push_back(r);
        }
    });
    m.def("search_state", [](const BattleContext &b) {
        py::dict d;d["cards_drawn"]=b.cardsDrawn;d["energy_wasted"]=b.energyWasted;
        auto hp=b.victoryHpRelics.project(b.player.curHp,b.player.maxHp);
        d["victory_hp"]=hp.curHp;d["victory_max_hp"]=hp.maxHp;
        d["centennial_puzzle_used"]=!b.player.hasRelic<RelicId::CENTENNIAL_PUZZLE>();
        return d;
    });
    m.def("import_start_selection", [](BattleContext &b, const py::dict &d) {
        b.inputState=InputState::CARD_SELECT;
        b.cardSelectInfo=CardSelectInfo{};
        auto task=d["task"].cast<std::string>();
        if(task=="TOOLBOX") {
            b.cardSelectInfo.cardSelectTask=CardSelectTask::DISCOVERY;
            b.cardSelectInfo.cards=d["cards"].cast<std::array<CardId,3>>();
            b.cardSelectInfo.data0=1;
            b.cardSelectInfo.discoveryZeroCost=false;
            b.cardSelectInfo.discoveryFrameRng=false;
        } else if(task=="GAMBLING_CHIP") {
            b.cardSelectInfo.cardSelectTask=CardSelectTask::GAMBLE;
        } else throw std::invalid_argument("unsupported start selection");
        for(auto value:d["queue"].cast<py::list>()) {
            auto a=value.cast<py::dict>();auto kind=a["kind"].cast<std::string>();
            if(kind=="draw")b.addToBot(Actions::DrawCards(a["amount"].cast<int>()));
            else if(kind=="block")b.addToBot(Actions::GainBlock(a["amount"].cast<int>()));
            else if(kind=="energy")b.addToBot(Actions::GainEnergy(a["amount"].cast<int>()));
            else if(kind=="power")b.addToBot(queuedPower(a));
            else if(kind=="damage_all")b.addToBot(Actions::DamageAllEnemy(a["amount"].cast<int>()));
            else if(kind=="make_draw")b.addToBot(Actions::MakeTempCardInDrawPile(CardInstance(a["card"].cast<CardId>()),a["amount"].cast<int>(),a["shuffle"].cast<bool>()));
            else if(kind=="red_skull")b.addToBot(Action{[](BattleContext &next) {
                auto &p=next.player;
                // RedSkull$1 adds Strength directly and sets its private flag.
                if (!p.redSkullActive && p.isBloodied) {
                    p.buff<PS::STRENGTH>(3);
                    p.redSkullActive=true;
                }
            }});
            else if(kind=="gamble")b.addToBot(Actions::GambleAction());
            else throw std::invalid_argument("unsupported pending queue action");
        }
    });
    m.def("run_rng", &liveRunRng);
    m.def("recover_run_after_battle", [](const BattleContext &prediction, GameContext &run, bool won) {
        // Called only after the real game has ended this battle and the
        // predicted outcome disagreed. Preserve the disagreement in the log;
        // rebuild the native continuation, then import the real run resources.
        BattleContext completed(prediction);
        completed.outcome=won?Outcome::PLAYER_VICTORY:Outcome::PLAYER_LOSS;
        completed.exitBattle(run);
    });
    m.def("live_catalog", [](){py::dict d;d["events"]=std::vector<std::string>(std::begin(eventIdStrings),std::end(eventIdStrings));d["encounters"]=std::vector<std::string>(std::begin(monsterEncounterStrings),std::end(monsterEncounterStrings));return d;});
    m.def("selection_info", [](const BattleContext &battle) {
        if (battle.inputState != InputState::CARD_SELECT)
            throw std::invalid_argument("battle has no pending card selection");
        const auto &info = battle.cardSelectInfo;
        py::dict out;
        out["task"] = cardSelectTaskStrings[static_cast<int>(info.cardSelectTask)];
        out["pick_count"] = info.pickCount;
        out["selected_indices"] = info.selectedIndices;
        const char *pile = nullptr;
        switch (info.cardSelectTask) {
            case CardSelectTask::CODEX:
            case CardSelectTask::DISCOVERY:
                out["generated_cards"] = std::vector<CardId>(info.cards.begin(), info.cards.end());
                break;
            case CardSelectTask::HEADBUTT:
            case CardSelectTask::HOLOGRAM:
            case CardSelectTask::LIQUID_MEMORIES_POTION:
            case CardSelectTask::MEDITATE: pile = "discard_pile"; break;
            case CardSelectTask::EXHUME: pile = "exhaust_pile"; break;
            case CardSelectTask::SECRET_TECHNIQUE:
            case CardSelectTask::SECRET_WEAPON:
            case CardSelectTask::SEEK: pile = "draw_pile"; break;
            case CardSelectTask::INVALID:
                throw std::invalid_argument("invalid card selection task");
            default: pile = "hand"; break;
        }
        if (pile) out["source_pile"] = pile;
        return out;
    });
    m.def("plan_reusing", [](const BattleContext &root, int simulations, double bossMultiplier) {
        if (root.outcome != Outcome::UNDECIDED ||
            (root.inputState != InputState::PLAYER_NORMAL && root.inputState != InputState::CARD_SELECT))
            throw std::invalid_argument("plan_reusing requires a living decision boundary");
        BattleContext predicted(root);
        // Keep the GIL: this engine has process-global mutable diagnostic
        // counters. Each live runner is single-threaded and owns one instance.
        const auto result = combat_search::playoutReusing(predicted, simulations, bossMultiplier);
        py::dict out;
        out["actions"] = result.actions;
        out["simulations"] = result.simulations;
        out["outcome"] = static_cast<int>(predicted.outcome);
        out["hp"] = predicted.player.curHp;
        out["max_hp"] = predicted.player.maxHp;
        out["turns"] = predicted.turn + 1;
        out["search_rounds"] = result.rounds;
        out["reused_trees"] = result.reusedTrees;
        out["reused_visits"] = result.reusedVisits;
        return out;
    }, py::arg("battle"), py::arg("simulations") = 32000, py::arg("boss_multiplier") = 12.0,
    "Run the unchanged P300 reuse policy on a copy of an imported battle; return its executable plan.");
}
