#pragma once
#include "game/GameContext.h"
#include "sim/search/GameAction.h"

// This importer assigns storage, without invoking obtain/on-equip callbacks.
// Pending native continuations are retained when the Java screen is equivalent.
static void syncLiveRun(sts::GameContext &g, const py::dict &d) {
 using namespace sts;
#define SET(k,m,T) if(d.contains(k)) g.m=py::cast<T>(d[k]);
 SET("screen",screenState,ScreenState)
 if(d.contains("event"))g.curEvent=static_cast<Event>(d["event"].cast<int>());
 SET("room",curRoom,Room) SET("last_room",lastRoom,Room)
 SET("boss",boss,MonsterEncounter) SET("second_boss",secondBoss,MonsterEncounter)
 SET("hp",curHp,int) SET("max_hp",maxHp,int) SET("gold",gold,int)
 SET("act",act,int) SET("floor",floorNum,int) SET("x",curMapNodeX,int) SET("y",curMapNodeY,int)
 SET("red",redKey,bool) SET("green",greenKey,bool) SET("blue",blueKey,bool)
 SET("potion_capacity",potionCapacity,int) SET("shop_remove_count",shopRemoveCount,int)
 SET("card_rarity_factor",cardRarityFactor,int) SET("potion_chance",potionChance,int)
 SET("monster_chance",monsterChance,float) SET("shop_chance",shopChance,float) SET("treasure_chance",treasureChance,float)
 SET("speedrun",speedrunPace,bool)
#undef SET
 if(d.contains("deck")) {
  g.deck=Deck{};
  for(auto item:d["deck"].cast<py::list>()) {
   auto c=item.cast<py::dict>();auto value=c["card"].cast<Card>();
   g.deck.obtainRaw(value);
   if(c["bottled"].cast<bool>())g.deck.bottleCard(g.deck.size()-1,value.getType());
  }
 }
 if(d.contains("relics")){g.relics=RelicContainer{};for(auto item:d["relics"].cast<py::list>()){auto r=item.cast<py::tuple>();g.relics.add({r[0].cast<RelicId>(),r[1].cast<int>()});}}
 if(d.contains("potions")){g.potionCount=0;g.potions.fill(Potion::EMPTY_POTION_SLOT);int i=0;for(auto item:d["potions"].cast<py::list>()){if(i>=5)throw std::invalid_argument("too many potion slots");auto p=static_cast<Potion>(item.cast<int>());g.potions[i++]=p;if(p!=Potion::EMPTY_POTION_SLOT)++g.potionCount;}}
 if(d.contains("rng")){auto rng=d["rng"].cast<py::dict>();
#define RNG(n,m) if(rng.contains(n)){auto r=rng[n].cast<py::dict>();g.m.seed0=r["seed0"].cast<uint64_t>();g.m.seed1=r["seed1"].cast<uint64_t>();g.m.counter=r["counter"].cast<int>();}
 RNG("aiRng",aiRng) RNG("cardRandomRng",cardRandomRng) RNG("cardRng",cardRng) RNG("eventRng",eventRng)
 RNG("merchantRng",merchantRng) RNG("miscRng",miscRng) RNG("monsterHpRng",monsterHpRng) RNG("monsterRng",monsterRng)
 RNG("potionRng",potionRng) RNG("relicRng",relicRng) RNG("shuffleRng",shuffleRng) RNG("treasureRng",treasureRng)
 RNG("neowRng",neowRng) RNG("mathUtilRng",mathUtilRng)
#undef RNG
 }
 if(d.contains("map")) {g.map=std::make_shared<Map>();for(int y=0;y<15;++y)for(int x=0;x<7;++x){g.map->nodes[y][x].x=x;g.map->nodes[y][x].y=y;}
  for(auto item:d["map"].cast<py::list>()){auto n=item.cast<py::dict>();int x=n["x"].cast<int>(),y=n["y"].cast<int>();if(y<0||y>=15||x<0||x>=7)throw std::invalid_argument("map node outside native bounds");auto &node=g.map->nodes[y][x];node.room=n["room"].cast<Room>();for(auto e:n["edges"].cast<py::list>())node.addEdge(e.cast<int>());}
  g.map->normalizeParents();auto flame=d["burning"].cast<std::array<int,3>>();g.map->burningEliteX=flame[0];g.map->burningEliteY=flame[1];g.map->burningEliteBuff=flame[2];
 }
#define VEC(k,m,T) if(d.contains(k))g.m=d[k].cast<std::vector<T>>();
 #define EVENTS(k,m) if(d.contains(k)){g.m.clear();for(auto v:d[k].cast<std::vector<int>>())g.m.push_back(static_cast<Event>(v));}
 EVENTS("event_list",eventList) EVENTS("shrine_list",shrineList) EVENTS("one_time_events",specialOneTimeEventList)
 #undef EVENTS
 VEC("common_pool",commonRelicPool,RelicId) VEC("uncommon_pool",uncommonRelicPool,RelicId) VEC("rare_pool",rareRelicPool,RelicId) VEC("shop_pool",shopRelicPool,RelicId) VEC("boss_pool",bossRelicPool,RelicId)
#undef VEC
 if(d.contains("monster_list")){g.monsterList={};g.monsterListOffset=0;for(auto v:d["monster_list"].cast<std::vector<MonsterEncounter>>())g.monsterList.push_back(v);}
 if(d.contains("elite_list")){g.eliteMonsterList={};g.eliteMonsterListOffset=0;for(auto v:d["elite_list"].cast<std::vector<MonsterEncounter>>())g.eliteMonsterList.push_back(v);}
 if(d.contains("info")){auto i=d["info"].cast<py::dict>();
#define INFO(k,m,T) if(i.contains(k))g.info.m=i[k].cast<T>();
 INFO("encounter",encounter,MonsterEncounter) INFO("phase",phase,int) INFO("event_data",eventData,int)
 INFO("hp0",hpAmount0,int) INFO("hp1",hpAmount1,int) INFO("hp2",hpAmount2,int)
 INFO("gold_loss",goldLoss,int) INFO("gold",gold,int) INFO("match_first",matchFirst,int)
 INFO("upgrade_one",upgradeOne,bool) INFO("cleanup_remove",cleanUpIsRemoveCard,bool)
 INFO("potion_index",potionIdx,int) INFO("card_index",cardIdx,int)
 INFO("relic0",relicIdx0,int) INFO("relic1",relicIdx1,int)
 INFO("fall_skill",skillCardDeckIdx,int) INFO("fall_power",powerCardDeckIdx,int) INFO("fall_attack",attackCardDeckIdx,int)
 if(i.contains("select_type"))g.info.selectScreenType=static_cast<CardSelectScreenType>(i["select_type"].cast<int>());
 INFO("select_count",toSelectCount,int)
 INFO("select_cancel",selectCancelReturn,ScreenState)
#undef INFO
 }
 if(d.contains("neow")){int j=0;for(auto item:d["neow"].cast<py::list>()){auto v=item.cast<py::tuple>();g.info.neowRewards.at(j++)={static_cast<Neow::Bonus>(v[0].cast<int>()),static_cast<Neow::Drawback>(v[1].cast<int>())};}}
 if(d.contains("selection")){g.info.toSelectCards.clear();for(auto item:d["selection"].cast<py::list>()){auto c=item.cast<py::tuple>();g.info.toSelectCards.emplace_back(c[0].cast<Card>(),c[1].cast<int>());}}
 if(d.contains("selected")){auto selected=d["selected"].cast<py::list>();if(selected.size()>3)throw std::invalid_argument("more than three selected run cards");g.info.haveSelectedCards.clear();for(auto item:selected){auto c=item.cast<py::tuple>();g.info.haveSelectedCards.push_back({c[0].cast<Card>(),c[1].cast<int>()});}}
 if(d.contains("rewards")){auto r=d["rewards"].cast<py::dict>();g.info.rewardsContainer=Rewards{};auto &out=g.info.rewardsContainer;
  for(auto v:r["gold"].cast<std::vector<int>>())out.addGold(v);
  for(auto v:r["relics"].cast<std::vector<RelicId>>())out.addRelic(v);
  for(auto v:r["potions"].cast<std::vector<int>>())out.addPotion(static_cast<Potion>(v));
  for(auto cs:r["cards"].cast<std::vector<std::vector<Card>>>()){CardReward group;for(auto c:cs)group.push_back(c);out.addCardReward(group);}
  out.emeraldKey=r["emerald"].cast<bool>();out.sapphireKey=r["sapphire"].cast<bool>();
 }
 if(d.contains("boss_relics")){auto a=d["boss_relics"].cast<std::array<RelicId,3>>();std::copy(a.begin(),a.end(),g.info.bossRelics);}
 if(d.contains("shop")){auto s=d["shop"].cast<py::dict>();auto &out=g.info.shop;
#define STOCK(k,m,T,N) {auto a=s[k].cast<std::array<T,N>>();std::copy(a.begin(),a.end(),out.m);}
 STOCK("cards",cards,Card,7) STOCK("relics",relics,RelicId,3) STOCK("prices",prices,int,13)
 {auto a=s["potions"].cast<std::array<int,3>>();for(int j=0;j<3;++j)out.potions[j]=static_cast<Potion>(a[j]);}
#undef STOCK
 out.removeCost=s["remove"].cast<int>();}
}

static py::dict liveRunRng(const sts::GameContext &g){py::dict out;
#define R(n,m) {py::dict r;r["seed0"]=g.m.seed0;r["seed1"]=g.m.seed1;r["counter"]=g.m.counter;out[n]=r;}
 R("aiRng",aiRng) R("cardRandomRng",cardRandomRng) R("cardRng",cardRng) R("eventRng",eventRng)
 R("merchantRng",merchantRng) R("miscRng",miscRng) R("monsterHpRng",monsterHpRng) R("monsterRng",monsterRng)
 R("potionRng",potionRng) R("relicRng",relicRng) R("shuffleRng",shuffleRng) R("treasureRng",treasureRng)
 R("neowRng",neowRng) R("mathUtilRng",mathUtilRng)
#undef R
 return out;
}
