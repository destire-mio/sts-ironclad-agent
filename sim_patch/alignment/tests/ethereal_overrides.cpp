#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using namespace sts;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static BattleContext fixture(const std::vector<CardId> &hand) {
    GameContext g(CharacterClass::IRONCLAD, 1298, 20); g.floorNum = 1;
    BattleContext b; b.init(g, MonsterEncounter::CULTIST); b.cards = CardManager();
    b.player.block = 0;
    for (auto id : hand) b.cards.createTempCardInHand(CardInstance(id));
    return b;
}
static void settle(BattleContext &b) { b.setState(InputState::EXECUTING_ACTIONS); b.executeActions(); }
static std::vector<CardId> exhausted(const BattleContext &b) {
    std::vector<CardId> result; for (const auto &c : b.cards.exhaustPile) result.push_back(c.id); return result;
}
static void discard(BattleContext &b) { b.discardAtEndOfTurn(); settle(b); }
int main(int argc, char **argv) {
    using C = CardId;
    try {
        std::string name = argc > 1 ? argv[1] : "";
        if (name == "entrench_order") {
            auto b = fixture({C::DAZED, C::ASCENDERS_BANE, C::APPARITION, C::ENTRENCH}); discard(b);
            check(exhausted(b) == std::vector<C>{C::APPARITION, C::ASCENDERS_BANE, C::DAZED}, "Entrench last: original exhaust order differs");
            auto other = fixture({C::ENTRENCH, C::DAZED, C::ASCENDERS_BANE, C::APPARITION}); discard(other);
            check(exhausted(other) == std::vector<C>{C::ASCENDERS_BANE, C::APPARITION, C::DAZED}, "Entrench first: original exhaust order differs");
        } else if (name == "armor_order") {
            auto b = fixture({C::GHOSTLY_ARMOR, C::DAZED, C::ASCENDERS_BANE}); discard(b);
            check(exhausted(b) == std::vector<C>{C::DAZED, C::ASCENDERS_BANE, C::GHOSTLY_ARMOR}, "Ghostly Armor original exhaust order differs");
        } else if (name == "queued_copy") {
            auto b = fixture({C::DAZED, C::ASCENDERS_BANE, C::APPARITION, C::ENTRENCH});
            b.discardAtEndOfTurn(); auto copy = b;
            check(b.cards.cardsInHand == 4 && b.cards.exhaustPile.empty(), "bulk exhaustion happened before queue execution");
            settle(b); check(copy.cards.cardsInHand == 4 && copy.cards.exhaustPile.empty(), "queued callback mutated sibling branch");
            settle(copy); check(exhausted(b) == exhausted(copy) && exhausted(b) == std::vector<C>{C::APPARITION, C::ASCENDERS_BANE, C::DAZED}, "copied bulk callback used the wrong hand");
        } else if (name == "current_hand") {
            auto b = fixture({C::ENTRENCH}); b.discardAtEndOfTurn(); auto copy = b;
            b.cards.createTempCardInHand(CardInstance(C::APPARITION));
            copy.cards.createTempCardInHand(CardInstance(C::DAZED));
            settle(b); settle(copy);
            check(exhausted(b) == std::vector<C>{C::APPARITION} && exhausted(copy) == std::vector<C>{C::DAZED}, "bulk callback did not inspect each executing branch's hand");
        } else if (name == "duplicate_callbacks") {
            auto b = fixture({C::GHOSTLY_ARMOR, C::ENTRENCH, C::DAZED, C::ASCENDERS_BANE});
            b.player.buff<PS::FEEL_NO_PAIN>(3); discard(b);
            auto ids = exhausted(b); std::sort(ids.begin(), ids.end());
            std::vector<C> expected{C::GHOSTLY_ARMOR, C::DAZED, C::ASCENDERS_BANE}; std::sort(expected.begin(), expected.end());
            check(ids == expected && b.player.block == 9, "duplicate callbacks exhausted a card twice or skipped its effect");
            check(b.cards.discardPile.size() == 1 && b.cards.discardPile[0].id == C::ENTRENCH, "non-Ethereal Entrench was exhausted");
        } else if (name == "retained_control") {
            auto b = fixture({C::GHOSTLY_ARMOR, C::DAZED, C::ASCENDERS_BANE}); b.cards.hand[0].retain = true; discard(b);
            check(b.cards.cardsInHand == 1 && b.cards.hand[0].id == C::GHOSTLY_ARMOR && b.cards.exhaustPile.size() == 2,
                  "retained Ghostly Armor was processed by end-turn callback");
        } else if (name == "pyramid_control") {
            auto b = fixture({C::ENTRENCH, C::DEFEND_RED}); b.player.setHasRelic<R::RUNIC_PYRAMID>(true); discard(b);
            check(b.cards.cardsInHand == 2 && b.cards.exhaustPile.empty() && b.cards.discardPile.empty(), "empty bulk action affected Pyramid hand");
        } else if (name == "generic_control") {
            auto b = fixture({C::DAZED, C::ASCENDERS_BANE, C::APPARITION}); discard(b);
            check(exhausted(b) == std::vector<C>{C::ASCENDERS_BANE, C::DAZED, C::APPARITION}, "generic callback order changed");
        } else if (name == "free_flag") {
            for (auto id : {C::GHOSTLY_ARMOR, C::CARNAGE}) {
                auto b = fixture({id}); b.cards.hand[0].freeToPlayOnce = true;
                b.exhaustSpecificCardInHand(0, b.cards.hand[0].uniqueId);
                check(b.cards.exhaustPile.size() == 1 && !b.cards.exhaustPile[0].freeToPlayOnce, "specific exhaustion retained one-use free flag");
                b.chooseExhumeCard(0); b.player.energy = 0;
                check(b.cards.cardsInHand == 1 && !search::Action(search::ActionType::CARD, 0, 0).isValidAction(b), "retrieved card was playable without required energy");
            }
        } else if (name == "discard_flag_control") {
            auto b = fixture({C::STRIKE_RED}); b.cards.hand[0].freeToPlayOnce = true; discard(b);
            check(b.cards.exhaustPile.empty() && b.cards.discardPile.size() == 1 && b.cards.discardPile[0].freeToPlayOnce,
                  "ordinary end-turn discard cleared the Forethought flag");
        } else throw std::runtime_error("unknown Ethereal override case");
        std::cout << name << " passed\n"; return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
