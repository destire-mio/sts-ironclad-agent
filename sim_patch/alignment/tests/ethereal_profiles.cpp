#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include <nlohmann/json.hpp>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace sts;
using json = nlohmann::json;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static const std::vector<CardId> mixed{CardId::DAZED, CardId::DEFEND_RED, CardId::ASCENDERS_BANE,
                                      CardId::STRIKE_RED, CardId::APPARITION};
static BattleContext fixture(const std::vector<CardId> &hand = mixed) {
    GameContext g(CharacterClass::IRONCLAD, 123, 20); g.floorNum = 5;
    BattleContext b; b.init(g, MonsterEncounter::CULTIST);
    b.cards = CardManager(); b.player.energy = 3;
    for (auto id : hand) b.cards.createTempCardInHand(CardInstance(id));
    return b;
}
static void settle(BattleContext &b) { b.setState(InputState::EXECUTING_ACTIONS); b.executeActions(); }
static std::vector<CardId> exhausted(const BattleContext &b) {
    std::vector<CardId> ids; for (const auto &c : b.cards.exhaustPile) ids.push_back(c.id); return ids;
}
static json shuffleCase(const json &golden, const char *seed, int n) {
    for (const auto &row : golden["shuffles"])
        if (row["seed"] == seed && row["size"] == n) return row;
    throw std::runtime_error("missing independent JRE shuffle case");
}
static std::vector<CardId> exhaustOrder(const json &row, const std::vector<CardId> &hand) {
    std::vector<CardId> ids;
    auto order = row["order"].get<std::vector<int>>();
    for (auto i = order.rbegin(); i != order.rend(); ++i)
        if (CardInstance(hand[*i]).isEthereal()) ids.push_back(hand[*i]);
    return ids;
}
int main(int argc, char **argv) {
    try {
        check(argc == 3, "case and JRE golden file required");
        std::ifstream stream(argv[2]); json golden; stream >> golden;
        std::string name = argv[1];
        if (name == "installed_order") {
            const std::vector<CardId> ethereal{CardId::DAZED, CardId::ASCENDERS_BANE, CardId::APPARITION};
            auto three = fixture(ethereal); three.discardAtEndOfTurn(); settle(three);
            check(exhausted(three) == exhaustOrder(shuffleCase(golden, "399", 3), ethereal), "three-card Ethereal order differs from Java");
            auto b = fixture(); b.discardAtEndOfTurn(); settle(b);
            check(exhausted(b) == exhaustOrder(shuffleCase(golden, "399", 5), mixed), "installed Ethereal order differs from Java");
            check(b.cards.discardPile.size() == 2 && b.cards.discardPile[0].id == CardId::STRIKE_RED
                && b.cards.discardPile[1].id == CardId::DEFEND_RED, "ordinary discard order changed");
        } else if (name == "identity_shift") {
            auto b = fixture(); auto id = b.cards.hand[4].uniqueId;
            b.exhaustSpecificCardInHand(0, b.cards.hand[0].uniqueId);
            b.exhaustSpecificCardInHand(4, id);
            check(exhausted(b) == std::vector<CardId>{CardId::DAZED, CardId::APPARITION}, "shifted card was not found by identity");
            check(b.cards.cardsInHand == 3 && b.cards.hand[0].id == CardId::DEFEND_RED, "wrong card removed after hand shift");
        } else if (name == "queued_copy") {
            auto b = fixture(); b.discardAtEndOfTurn(); auto sibling = b;
            settle(b); check(sibling.cards.cardsInHand == 5 && sibling.cards.exhaustPile.empty(), "queue crossed branch boundary");
            settle(sibling); check(exhausted(b) == exhausted(sibling) && exhausted(b).size() == 3, "copy changed queued card identity");
        } else if (name == "retained") {
            auto b = fixture(); b.cards.hand[0].retain = true; b.discardAtEndOfTurn(); settle(b);
            std::vector<CardId> remaining(mixed.begin() + 1, mixed.end());
            check(exhausted(b) == exhaustOrder(shuffleCase(golden, "399", 4), remaining), "retained card participated in Ethereal shuffle");
            check(b.cards.cardsInHand == 1 && b.cards.hand[0].id == CardId::DAZED && !b.cards.hand[0].retain,
                  "retained Ethereal was exhausted or lost its reset");
        } else if (name == "pyramid") {
            auto b = fixture(); b.player.setHasRelic<RelicId::RUNIC_PYRAMID>(true);
            b.discardAtEndOfTurn(); settle(b);
            check(exhausted(b) == exhaustOrder(shuffleCase(golden, "399", 5), mixed), "Pyramid suppressed Ethereal processing");
            check(b.cards.cardsInHand == 2 && b.cards.hand[0].id == CardId::DEFEND_RED
                && b.cards.hand[1].id == CardId::STRIKE_RED && b.cards.discardPile.empty(), "Pyramid reordered or discarded ordinary cards");
#ifndef ETHEREAL_LEGACY_BASELINE
        } else if (name == "jre_random") {
            for (const auto &row : golden["shuffles"]) {
                java::Random rng(std::stoull(row["seed"].get<std::string>()));
                check(rng.rawSeed() == row["before"].get<std::uint64_t>(), "Java seed initialization differs");
                std::vector<int> values; for (int i = 0; i < row["size"].get<int>(); ++i) values.push_back(i);
                java::Collections::shuffleWithState(values.begin(), values.end(), rng);
                check(values == row["order"].get<std::vector<int>>() && rng.rawSeed() == row["after"].get<std::uint64_t>(), "Java shuffle values/state differ");
            }
            for (const auto &row : golden["bounded"]) {
                java::Random rng(0); rng.setRawSeed(row["before"].get<std::uint64_t>());
                for (int expected : row["values"].get<std::vector<int>>()) check(rng.nextInt(row["bound"].get<int>()) == expected, "Java bounded rejection differs");
                check(rng.rawSeed() == row["after"].get<std::uint64_t>(), "Java bounded rejection consumed wrong RNG state");
            }
        } else if (name == "shared_order_copy") {
            auto b = fixture(); const auto ref = shuffleCase(golden, "123", 5);
            b.endTurnShuffle.mode = EndTurnShuffleMode::JAVA_SHARED; b.endTurnShuffle.sharedRngInitialized = true;
            b.endTurnShuffle.sharedRng.setRawSeed(ref["before"].get<std::uint64_t>());
            auto sibling = b; b.discardAtEndOfTurn(); settle(b);
            check(exhausted(b) == exhaustOrder(ref, mixed), "shared Ethereal order differs from JRE");
            check(b.endTurnShuffle.sharedRng.rawSeed() == ref["after"].get<std::uint64_t>(), "shared Java state was not advanced");
            check(sibling.endTurnShuffle.sharedRng.rawSeed() == ref["before"].get<std::uint64_t>(), "RNG advance crossed branch boundary");
            sibling.discardAtEndOfTurn(); settle(sibling);
            check(exhausted(b) == exhausted(sibling) && b.endTurnShuffle.sharedRng.rawSeed() == sibling.endTurnShuffle.sharedRng.rawSeed(), "branch replay differs");
        } else if (name == "no_ethereal_rng") {
            for (int n : {0, 1, 5}) {
                auto b = fixture(std::vector<CardId>(n, CardId::DEFEND_RED)); auto ref = shuffleCase(golden, "123", n);
                b.endTurnShuffle.mode = EndTurnShuffleMode::JAVA_SHARED; b.endTurnShuffle.sharedRngInitialized = true;
                b.endTurnShuffle.sharedRng.setRawSeed(ref["before"].get<std::uint64_t>());
                b.discardAtEndOfTurn(); settle(b);
                check(b.endTurnShuffle.sharedRng.rawSeed() == ref["after"].get<std::uint64_t>() && b.cards.exhaustPile.empty(), "non-Ethereal shuffle consumed wrong RNG state");
            }
        } else if (name == "seeded_rng_control") {
            auto b = fixture(); b.endTurnShuffle.sharedRngInitialized = true; b.endTurnShuffle.sharedRng.setRawSeed(1999);
            auto ai = b.aiRng, card = b.cardRandomRng, misc = b.miscRng, shuffle = b.shuffleRng;
            b.discardAtEndOfTurn(); settle(b);
            auto same = [](const Random &a, const Random &c) { return a.seed0 == c.seed0 && a.seed1 == c.seed1 && a.counter == c.counter; };
            check(b.endTurnShuffle.sharedRng.rawSeed() == 1999 && same(ai,b.aiRng) && same(card,b.cardRandomRng)
                && same(misc,b.miscRng) && same(shuffle,b.shuffleRng), "seed-derived shuffle advanced unrelated RNG");
        } else if (name == "game_transfer") {
            GameContext g(CharacterClass::IRONCLAD, 123, 20); g.endTurnShuffle.mode = EndTurnShuffleMode::JAVA_SHARED;
            g.curRoom = Room::MONSTER; g.regainControlAction = [](GameContext &next) { next.afterBattle(); };
            g.endTurnShuffle.sharedRngInitialized = true; g.endTurnShuffle.sharedRng.setRawSeed(1999);
            BattleContext b; b.init(g, MonsterEncounter::CULTIST);
            check(b.endTurnShuffle.mode == g.endTurnShuffle.mode && b.endTurnShuffle.sharedRng.rawSeed() == 1999, "battle init lost reference profile");
            b.endTurnShuffle.sharedRng.nextInt(7); auto after = b.endTurnShuffle.sharedRng.rawSeed();
            check(g.endTurnShuffle.sharedRng.rawSeed() == 1999, "battle mutated parent GameContext RNG");
            b.outcome = Outcome::PLAYER_VICTORY; b.exitBattle(g);
            check(g.screenState == ScreenState::REWARDS, "battle did not enter combat rewards");
            BattleContext next; next.init(g, MonsterEncounter::CULTIST);
            check(next.endTurnShuffle.mode == EndTurnShuffleMode::JAVA_SHARED && next.endTurnShuffle.sharedRng.rawSeed() == after,
                  "next battle lost shared RNG continuation");
        } else if (name == "invalid_rng") {
            java::Random rng(0); auto before = rng.rawSeed(); bool failed = false;
            try { rng.setRawSeed(1ULL << 48); } catch (const std::invalid_argument &) { failed = true; }
            check(failed && rng.rawSeed() == before, "invalid raw seed changed state");
            for (int n : {0, -1}) { failed = false; try { rng.nextInt(n); } catch (const std::invalid_argument &) { failed = true; }
                check(failed && rng.rawSeed() == before, "invalid bound consumed RNG"); }
            auto b = fixture(); b.endTurnShuffle.mode = EndTurnShuffleMode::JAVA_SHARED;
            b.cards.hand[0].retain = true; failed = false;
            try { b.discardAtEndOfTurn(); } catch (const std::runtime_error &) { failed = true; }
            check(failed && b.cards.cardsInHand == 5 && b.actionQueue.isEmpty(), "missing observed RNG partially changed hand or queue");
#endif
        } else throw std::runtime_error("unknown Ethereal case");
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
