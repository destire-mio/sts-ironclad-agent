// Test-only lossless projection at pre-battle boundaries. Separate builds for q/r.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <nlohmann/json.hpp>
#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "sim/search/BattleScumSearcher2.h"
#include <cmath>
using json=nlohmann::json;
namespace sts {
template<typename T,int N> void to_json(json& j,const fixed_list<T,N>& v){j=json::array();for(const auto& x:v)j.push_back(x);}
template<typename T,int N> void from_json(const json& j,fixed_list<T,N>& v){if(j.size()>N)throw std::runtime_error("capacity");v.clear();for(const auto& x:j)v.push_back(x.get<T>());}
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Random,counter,seed0,seed1)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Card,id,misc,upgraded)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(RelicInstance,id,data)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(RelicContainer,relics,relicBits0,relicBits1,relicBits2)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Deck,cards,cardTypeCounts,bottleIdxs,upgradeableCount,transformableCount)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(MapNode,x,y,parentCount,parents,edgeCount,edges,room)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Map,burningEliteX,burningEliteY,burningEliteBuff,nodes)
}
using namespace sts;
#define GC_FIELDS(X) \
X(noteForYourselfCard) X(skipBattles) X(resolvingEscape) X(seed) \
X(aiRng) X(cardRandomRng) X(cardRng) X(eventRng) X(mathUtilRng) X(merchantRng) X(miscRng) X(monsterHpRng) X(monsterRng) X(neowRng) X(potionRng) X(relicRng) X(shuffleRng) X(treasureRng) \
X(eventList) X(shrineList) X(specialOneTimeEventList) X(commonRelicPool) X(uncommonRelicPool) X(rareRelicPool) X(shopRelicPool) X(bossRelicPool) X(colorlessCardPool) X(monsterListOffset) X(monsterList) X(eliteMonsterListOffset) X(eliteMonsterList) X(secondBoss) \
X(outcome) X(screenState) X(lastRoom) X(curEvent) X(curRoom) X(boss) X(monsterChance) X(shopChance) X(treasureChance) X(potionChance) X(cardRarityFactor) X(shopRemoveCount) X(speedrunPace) X(transformPreviewTimer) X(transformPreviewFrames) X(transformPreviewDelta) X(curMapNodeX) X(curMapNodeY) X(act) X(ascension) X(floorNum) X(cc) X(curHp) X(maxHp) X(gold) X(potionCount) X(potionCapacity) X(potions) X(relics) X(deck) X(blueKey) X(greenKey) X(redKey)
#define INFO_FIELDS(X) X(encounter) X(eventData) X(phase) X(hpAmount0) X(hpAmount1) X(hpAmount2) X(gold) X(goldLoss) X(bossRelics) X(stolenGold) X(allMonstersEscaped)
static json dump(const GameContext &g,bool continuation=false) {
 json j;
#define PUT(n) j[#n]=g.n;
 GC_FIELDS(PUT)
#undef PUT
#define PUT(n) j["info"][#n]=g.info.n;
 INFO_FIELDS(PUT)
#undef PUT
 j["map"]=*g.map;
 const auto &r=g.info.rewardsContainer;
 j["rewards"]={{"gold",r.gold},{"goldCount",r.goldRewardCount},{"cards",r.cardRewards},{"cardCount",r.cardRewardCount},{"relics",r.relics},{"relicCount",r.relicCount},{"potions",r.potions},{"potionCount",r.potionCount},{"emerald",r.emeraldKey},{"sapphire",r.sapphireKey}};
#ifdef COMBAT4R_IO
 j["endTurnShuffle"]={{"mode",int(g.endTurnShuffle.mode)},{"initialized",g.endTurnShuffle.sharedRngInitialized},{"seed",g.endTurnShuffle.sharedRng.rawSeed()}};
#endif
 if(continuation){
  if(g.screenState!=ScreenState::BATTLE)throw std::runtime_error("not prebattle");
  if(g.curRoom==Room::EVENT){
   if(g.curEvent!=Event::MINDBLOOM)throw std::runtime_error("unsupported event continuation");
   GameContext c(g); c.regainControl();
   j["continuation"]={{"kind","mindbloom"},{"relic",c.info.rewardsContainer.relics[0]},{"gold",c.info.rewardsContainer.gold[0]}};
  }else j["continuation"]={{"kind","afterBattle"}};
 }
 return j;
}
static GameContext load(const json &j){
 GameContext g;
#define GET(n) j.at(#n).get_to(g.n);
 GC_FIELDS(GET)
#undef GET
#define GET(n) j.at("info").at(#n).get_to(g.info.n);
 INFO_FIELDS(GET)
#undef GET
 g.map=std::make_shared<Map>(j.at("map").get<Map>());
 auto &r=g.info.rewardsContainer; const auto &jr=j.at("rewards");
 jr.at("gold").get_to(r.gold); jr.at("goldCount").get_to(r.goldRewardCount);
 jr.at("cards").get_to(r.cardRewards); jr.at("cardCount").get_to(r.cardRewardCount);
 jr.at("relics").get_to(r.relics); jr.at("relicCount").get_to(r.relicCount);
 jr.at("potions").get_to(r.potions); jr.at("potionCount").get_to(r.potionCount);
 jr.at("emerald").get_to(r.emeraldKey); jr.at("sapphire").get_to(r.sapphireKey);
#ifdef COMBAT4R_IO
 if(j.contains("endTurnShuffle")){auto &s=j.at("endTurnShuffle");g.endTurnShuffle.mode=static_cast<EndTurnShuffleMode>(s.at("mode").get<int>());g.endTurnShuffle.sharedRngInitialized=s.at("initialized");g.endTurnShuffle.sharedRng.setRawSeed(s.at("seed"));}
#endif
 auto c=j.at("continuation");
 if(c.at("kind")=="mindbloom"){
  const auto relic=c.at("relic").get<RelicId>(); const int gold=c.at("gold");
  g.regainControlAction=[relic,gold](GameContext &g){Rewards r;r.addGold(gold);r.addRelic(relic);g.addPotionRewards(r);r.addCardReward(g.createCardReward(Room::EVENT));g.openCombatRewardScreen(r);g.regainControlAction=[](GameContext &n){n.screenState=ScreenState::MAP_SCREEN;};};
 }else g.regainControlAction=[](GameContext &n){n.afterBattle();};
 return g;
}
PYBIND11_MODULE(paired_io,m){
 m.def("dump",[](const GameContext &g,bool continuation){return dump(g,continuation).dump();},pybind11::arg("game"),pybind11::arg("continuation")=false);
 m.def("load",[](const std::string &s){return load(json::parse(s));});
#ifdef COMBAT4R_IO
 m.def("terminal_metrics",[](const GameContext &g,const BattleContext &b,int initialMaxHp){
  const bool victory=b.outcome==Outcome::PLAYER_VICTORY;
  const auto projected= b.victoryHpRelics.project(b.player.curHp,b.player.maxHp);
  auto settled=g;settled.curHp=b.player.curHp;settled.maxHp=b.player.maxHp;b.updateRelicsOnExit(settled);
  using S=search::BattleScumSearcher2;
  const double oldScore=S::evaluateEndState4q(b)+(victory?100.0*std::max(0,b.player.maxHp-initialMaxHp):0.0);
  return json{{"raw_hp",b.player.curHp},{"raw_max_hp",b.player.maxHp},{"victory",victory},
   {"projected_hp",victory?projected.curHp:b.player.curHp},{"settled_hp",settled.curHp},
   {"score_before_hp_projection",oldScore},{"score_after_hp_projection",S::evaluateEndState4r(b,initialMaxHp)}}.dump();
 });
#endif
}
