#pragma once

#include "game/GameContext.h"
#include "game/Game.h"
#include "constants/SaveFileMappings.h"
#include "sim/search/GameAction.h"
#include <fstream>

using namespace sts;
using json = nlohmann::json;
using GA = search::GameAction;
using RT = GA::RewardsActionType;

static const char *types[] = {"GOLD","RELIC","POTION","CARD","SAPPHIRE_KEY","EMERALD_KEY"};
static json card(const Card &c, bool bottled=false) {
    return {{"id",c.id},{"upgrades",c.getUpgraded()},
        {"misc",c.id==CardId::RITUAL_DAGGER ? c.misc : 0},{"bottled",bottled}};
}
static json snapshot(const GameContext &g) {
    json out = {{"floor",g.floorNum},{"hp",g.curHp},{"max_hp",g.maxHp},{"gold",g.gold},
        {"keys",{{"blue",g.blueKey},{"green",g.greenKey},{"red",g.redKey}}},
        {"deck",json::array()},{"relics",json::array()},{"potions",json::array()},{"rng",json::object()}};
    for (int i=0;i<g.deck.size();++i) out["deck"].push_back(card(g.deck.cards[i],g.deck.isCardBottled(i)));
    for (auto r:g.relics.relics) out["relics"].push_back({{"id",r.id},{"counter",r.data}});
    for (int i=0;i<g.potionCapacity;++i) out["potions"].push_back(g.potions[i]);
    for (auto p : std::initializer_list<std::pair<const char*,const Random*>>{
        {"aiRng",&g.aiRng},{"monsterHpRng",&g.monsterHpRng},{"shuffleRng",&g.shuffleRng},
        {"cardRandomRng",&g.cardRandomRng},{"miscRng",&g.miscRng},{"potionRng",&g.potionRng},
        {"relicRng",&g.relicRng},{"cardRng",&g.cardRng},{"merchantRng",&g.merchantRng},{"treasureRng",&g.treasureRng}})
        out["rng"][p.first]={{"seed0",p.second->seed0},{"seed1",p.second->seed1},{"counter",p.second->counter}};
    out["reward_state"]={{"potion_chance",g.potionChance},{"card_rarity_factor",g.cardRarityFactor},
        {"card_upgraded_chance",getUpgradedCardChance(g.act,g.ascension)}};
    const bool grid=g.screenState==ScreenState::CARD_SELECT;
    out["phase"]=grid?"grid":(g.screenState==ScreenState::REWARDS?"rewards":
        (g.screenState==ScreenState::TREASURE_ROOM?"chest":(g.screenState==ScreenState::MAP_SCREEN?"map":"outside")));
    // The original Gson serializer omits null chest metadata after opening.
    if (g.screenState==ScreenState::TREASURE_ROOM) {
        const char *sizes[]={"SmallChest","MediumChest","LargeChest"};
        const char *tiers[]={"COMMON_RELIC","UNCOMMON_RELIC","RARE_RELIC"};
        out["chest"]={{"size",sizes[static_cast<int>(g.info.chestSize)]},{"has_gold",g.info.haveGold},
            {"relic_tier",tiers[static_cast<int>(g.info.tier)]}};
    }
    out["selection"]={{"count",grid?g.info.toSelectCount:0},{"choices",json::array()}};
    if (grid) for (auto c:g.info.toSelectCards)
        out["selection"]["choices"].push_back(card(c.card,c.deckIdx>=0&&g.deck.isCardBottled(c.deckIdx)));
    auto &groups=out["reward_groups"]=json::object(); out["reward_order"]=json::array();
    for (auto type:types) groups[type]=json::array();
    if (grid || g.screenState==ScreenState::REWARDS) {
        const auto &r=g.info.rewardsContainer;
        for (int i=0;i<r.goldRewardCount;++i) groups["GOLD"].push_back({{"gold",r.gold[i]}});
        for (int i=0;i<r.relicCount;++i) groups["RELIC"].push_back({{"id",r.relics[i]},
            {"linked_to_key",r.sapphireKey&&i==r.relicCount-1}});
        for (int i=0;i<r.potionCount;++i) groups["POTION"].push_back({{"id",r.potions[i]}});
        for (int i=0;i<r.cardRewardCount;++i) {
            json cards=json::array(); for (auto c:r.cardRewards[i]) cards.push_back(card(c));
            groups["CARD"].push_back({{"cards",cards}});
        }
        if (r.sapphireKey) groups["SAPPHIRE_KEY"].push_back({{"relic_index",r.relicCount-1}});
        if (r.emeraldKey) groups["EMERALD_KEY"].push_back(json::object());
    }
    for (auto type:types) for (int i=0;i<groups[type].size();++i)
        out["reward_order"].push_back({{"type",type},{"index",i}});
    return out;
}

