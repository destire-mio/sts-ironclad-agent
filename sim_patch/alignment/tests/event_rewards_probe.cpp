#include "combat/BattleContext.h"
#include "constants/SaveFileMappings.h"
#include "game/GameContext.h"
#include "game/Game.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"
#include <fstream>
#include <memory>
#include <sstream>

using namespace sts;
using json = nlohmann::json;
static bool selectionAudit = false;

static json rng(const Random &r) {
    return {{"seed0", r.seed0}, {"seed1", r.seed1}, {"counter", r.counter}};
}
static json card(const CardInstance &c) {
    return {{"id", c.id}, {"upgrades", c.getUpgradeCount()}, {"cost", c.costForTurn},
            {"base_cost", c.cost}, {"free_to_play_once", c.freeToPlayOnce}};
}
static json combatSnapshot(const GameContext &g, const BattleContext *b) {
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

static json deckCard(const Card &c, bool bottled=false) {
    return {{"id",c.id},{"upgrades",c.getUpgraded()},
        {"misc",c.id==CardId::RITUAL_DAGGER ? c.misc : 0},{"bottled",bottled}};
}
static json rewards(const Rewards &r) {
    json out = json::array();
    for (int i=0; i<r.goldRewardCount; ++i) out.push_back({{"type","GOLD"},{"gold",r.gold[i]}});
    for (int i=0; i<r.relicCount; ++i) out.push_back({{"type","RELIC"},{"id",r.relics[i]}});
    for (int i=0; i<r.potionCount; ++i) out.push_back({{"type","POTION"},{"id",r.potions[i]}});
    for (int i=0; i<r.cardRewardCount; ++i) {
        json cards = json::array();
        for (auto c : r.cardRewards[i]) cards.push_back(deckCard(c));
        out.push_back({{"type","CARD"},{"cards",cards}});
    }
    return out;
}
static json snapshot(const GameContext &g, const BattleContext *b) {
    json out = combatSnapshot(g, b);
    out["native_attack_count"] = b ? json(b->player.attacksPlayedThisTurn) : json(nullptr);
    out["deck"] = json::array(); out["relics"] = json::array();
    out["potions"] = json::array(); out["rewards"] = json::array();
    for (int i=0;i<g.deck.size();++i) out["deck"].push_back(deckCard(g.deck.cards[i],g.deck.isCardBottled(i)));
    for (auto r:g.relics.relics) out["relics"].push_back({{"id",r.id},{"counter",r.data}});
    for (int i=0;i<g.potionCapacity;++i) out["potions"].push_back(b ? b->potions[i] : g.potions[i]);
    out["reward_state"] = {{"potion_chance",g.potionChance},{"card_rarity_factor",g.cardRarityFactor},
        {"card_upgraded_chance",getUpgradedCardChance(g.act, g.ascension)}};
    if (g.screenState==ScreenState::REWARDS && !b) out["rewards"] = rewards(g.info.rewardsContainer);
    if (selectionAudit) {
        const bool selecting = !b && g.screenState==ScreenState::CARD_SELECT;
        json choices = json::array();
        if (selecting) for (auto c : g.info.toSelectCards)
            choices.push_back(deckCard(c.card, c.deckIdx>=0 && g.deck.isCardBottled(c.deckIdx)));
        out["selection_state"] = {{"selecting",selecting},
            {"count",selecting ? g.info.toSelectCount : 0}, {"choices",choices},
            {"pending_rewards",!b && (selecting || g.screenState==ScreenState::REWARDS)
                ? rewards(g.info.rewardsContainer) : json::array()}};
    }
    return out;
}

// This observer sets only pre-event inputs. The production core executes all rules.
int main(int argc, char **argv) {
    try {
        if (argc != 2) throw std::runtime_error("one input file required");
        json q; std::ifstream(argv[1]) >> q;
        selectionAudit = q.value("selection_audit", false);
        const auto &spec = q.at("spec");
        const auto seed = spec.at("seed").get<std::uint64_t>();
        GameContext g(CharacterClass::IRONCLAD, seed, 20);
        g.act = spec.at("act"); g.floorNum = spec.at("floor");
        g.curHp = spec.at("hp"); g.maxHp = spec.at("max_hp"); g.gold = spec.at("gold");
        g.curRoom = Room::EVENT; g.curEvent = spec.at("id").get<Event>();
        if (g.curEvent == Event::INVALID) throw std::runtime_error("unknown event");
        g.regainControlAction = [](GameContext &g) { g.screenState = ScreenState::MAP_SCREEN; };
        g.deck = Deck();
        for (auto entry : q.at("initial_deck")) {
            Card c(entry.at("id").get<CardId>(), entry.at("upgrades").get<int>());
            if (c.id == CardId::RITUAL_DAGGER) c.misc = entry.at("misc");
            g.deck.obtainRaw(c);
            if (entry.at("bottled").get<bool>()) g.deck.bottleCard(g.deck.size()-1, c.getType());
        }
        g.relics = RelicContainer{};
        for (auto entry : q.at("initial_relics"))
            g.relics.add({entry.at("id").get<RelicId>(), entry.at("counter").get<int>()});
        // Seed both engines from the declared fixture, not from post-action observations.
        g.aiRng = g.monsterHpRng = g.shuffleRng = g.cardRandomRng = Random(seed + g.floorNum);
        g.potionRng = g.relicRng = g.cardRng = g.merchantRng = Random(seed);
        g.miscRng = Random(spec.at("misc_seed").get<std::uint64_t>());
        g.cardRarityFactor = 5; g.potionChance = 0;
        const auto &pools = q.at("pools");
        g.commonRelicPool = pools.at("common").get<std::vector<RelicId>>();
        g.uncommonRelicPool = pools.at("uncommon").get<std::vector<RelicId>>();
        g.rareRelicPool = pools.at("rare").get<std::vector<RelicId>>();
        g.shopRelicPool = pools.at("shop").get<std::vector<RelicId>>();
        g.bossRelicPool = pools.at("boss").get<std::vector<RelicId>>();
        json initial = snapshot(g, nullptr);
        initial["deck"] = json::array();
        for (int i=0; i<g.deck.size(); ++i) {
            const auto &c = g.deck.cards[i];
            initial["deck"].push_back({{"id",c.id},{"upgrades",c.getUpgraded()},
                {"misc",c.id == CardId::RITUAL_DAGGER ? c.misc : 0}, {"bottled",g.deck.isCardBottled(i)}});
        }
        initial["relics"] = json::array();
        for (auto r : g.relics.relics) initial["relics"].push_back({{"id",r.id},{"counter",r.data}});
        g.setupEvent();
        for (int index : spec.at("sim_choices")) {
            search::GameAction a(index);
            if (!a.isValidAction(g)) throw std::runtime_error("illegal event input");
            a.execute(g);
            if (g.screenState == ScreenState::BATTLE) break;
        }
        if (g.screenState != ScreenState::BATTLE) throw std::runtime_error("event did not enter battle");
        auto b = std::make_unique<BattleContext>(); b->init(g);
        json result = {{"initial", initial}, {"views",json::array({snapshot(g, b.get())})}};
        if (selectionAudit) result["copy_checks"] = json::array();
        for (const auto &step : q.at("steps")) {
            if (step.at("kind") == "grid") {
                if (b || g.screenState!=ScreenState::CARD_SELECT) throw std::runtime_error("grid action outside selection");
                search::GameAction a(step.at("index").get<int>());
                if (!a.isValidAction(g)) throw std::runtime_error("illegal grid action");
                const json parentBefore = snapshot(g, nullptr);
                GameContext child = g;
                a.execute(child);
                const json childAfter = snapshot(child, nullptr);
                if (snapshot(g, nullptr)!=parentBefore) throw std::runtime_error("child selection mutated parent");
                a.execute(g);
                if (snapshot(g, nullptr)!=childAfter) throw std::runtime_error("selection differs after copying context");
                if (selectionAudit) result["copy_checks"].push_back({{"step",result["views"].size()-1},
                    {"selected_index",step.at("index")}, {"parent_unchanged",true}, {"child_matches_uncopied_branch",true},
                    {"child_after",childAfter}});
                result["views"].push_back(snapshot(g, nullptr));
                continue;
            }
            if (step.at("kind") == "card_peek_skip") {
                if (b || g.screenState!=ScreenState::REWARDS) throw std::runtime_error("card UI close outside rewards");
                search::GameAction a(search::GameAction::RewardsActionType::CARD,step.value("index",0),0);
                if (!a.isValidAction(g)) throw std::runtime_error("card UI opens an unavailable reward");
                // Original SkipCardButton closes the UI without removing the reward.
                // The native atomic card choice has no separate open/close phase.
                result["views"].push_back(snapshot(g, nullptr));
                continue;
            }
            if (step.at("kind") == "reward") {
                if (b || g.screenState != ScreenState::REWARDS) throw std::runtime_error("reward action outside rewards");
                using RT = search::GameAction::RewardsActionType;
                const std::string type = step.at("type");
                RT t;
                if(type=="GOLD")t=RT::GOLD; else if(type=="RELIC")t=RT::RELIC;
                else if(type=="POTION")t=RT::POTION; else if(type=="CARD")t=RT::CARD;
                else if(type=="SKIP")t=RT::SKIP; else throw std::runtime_error("unsupported reward action");
                search::GameAction a(t, step.value("index",0), step.value("pick",0));
                if(!a.isValidAction(g)) throw std::runtime_error("illegal reward action: " + step.dump());
                a.execute(g);
                if(g.screenState==ScreenState::CARD_SELECT && !selectionAudit) throw std::runtime_error("unmapped relic selection");
                result["views"].push_back(snapshot(g, nullptr));
                continue;
            }
            const auto &value = step.at("command");
            std::istringstream line(value.get<std::string>());
            std::string kind; int index = 0, target = 0; line >> kind >> index >> target;
            if (!b) throw std::runtime_error("combat action outside battle");
            if (kind != "play" && kind != "end") throw std::runtime_error("unsupported combat command");
            search::Action a = kind == "end" ? search::Action(search::ActionType::END_TURN)
                : search::Action(search::ActionType::CARD, index-1, target);
            if (!a.isValidAction(*b)) throw std::runtime_error("illegal captured command: " + value.get<std::string>());
            a.execute(*b);
            if (b->outcome != Outcome::UNDECIDED) { b->exitBattle(g); b.reset(); }
            result["views"].push_back(snapshot(g, b.get()));
        }
        std::cout << result.dump() << '\n';
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
