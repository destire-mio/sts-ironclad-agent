#include "game/GameContext.h"
#include "game/Game.h"
#include "game/SaveFile.h"
#include "combat/BattleContext.h"
#include "constants/SaveFileMappings.h"
#include "sim/search/GameAction.h"
#include <fstream>
using namespace sts;
using json=nlohmann::json;
using GA=search::GameAction;
json card(const Card&c,bool bottled=false){return {{"id",c.id},{"upgrades",c.getUpgraded()},{"misc",c.id==CardId::RITUAL_DAGGER?c.misc:0},{"bottled",bottled}};}
Card parseCard(const json&j){auto id=(j.is_string()?j:j.at("id")).get<CardId>();if(id==CardId::INVALID)throw std::runtime_error("unknown card");Card c(id,j.is_string()?0:j.value("upgrades",0));if(j.is_object()&&j.contains("misc"))c.misc=j["misc"];return c;}
json snapshot(const GameContext&g){
 json out={{"hp",g.curHp},{"max_hp",g.maxHp},{"gold",g.gold},{"deck",json::array()},{"relics",json::array()},{"potions",json::array()},{"rewards",json::array()},{"selection_count",g.screenState==ScreenState::CARD_SELECT?g.info.toSelectCount:0},{"selection",json::array()},{"battle",g.screenState==ScreenState::BATTLE}};
 for(int i=0;i<g.deck.size();++i)out["deck"].push_back(card(g.deck.cards[i],g.deck.isCardBottled(i)));
 for(auto r:g.relics.relics)out["relics"].push_back({{"id",r.id},{"counter",r.data}});
 for(int i=0;i<g.potionCapacity;i++)out["potions"].push_back(g.potions[i]);
 if(g.screenState==ScreenState::CARD_SELECT)for(auto c:g.info.toSelectCards)out["selection"].push_back(card(c.card,c.deckIdx>=0&&g.deck.isCardBottled(c.deckIdx)));
 if(g.screenState==ScreenState::BATTLE)out["encounter"]=g.info.encounter;
 if(g.screenState==ScreenState::REWARDS){const auto&r=g.info.rewardsContainer;
  for(int i=0;i<r.goldRewardCount;i++)out["rewards"].push_back({{"type","GOLD"},{"gold",r.gold[i]}});
  for(int i=0;i<r.relicCount;i++)out["rewards"].push_back({{"type","RELIC"},{"id",r.relics[i]}});
  for(int i=0;i<r.potionCount;i++)out["rewards"].push_back({{"type","POTION"},{"id",r.potions[i]}});
  for(int i=0;i<r.cardRewardCount;i++){json cards=json::array();for(auto c:r.cardRewards[i])cards.push_back(card(c));out["rewards"].push_back({{"type","CARD"},{"cards",cards}});}
 }
 for(auto entry:std::initializer_list<std::pair<const char*,const Random*>>{{"miscRng",&g.miscRng},{"cardRng",&g.cardRng},{"cardRandomRng",&g.cardRandomRng},{"potionRng",&g.potionRng},{"relicRng",&g.relicRng},{"merchantRng",&g.merchantRng},{"shuffleRng",&g.shuffleRng}}){auto&r=*entry.second;out["rng"][entry.first]={{"counter",r.counter},{"seed0",r.seed0},{"seed1",r.seed1}};}
 return out;
}
int main(int argc,char**argv){try{
 json q;std::ifstream(argv[1])>>q;if(q.contains("save")){SaveFile saved(q["save"].dump(),CharacterClass::IRONCLAD);GameContext loaded;loaded.initFromSave(saved);std::cout<<snapshot(loaded).dump()<<'\n';return 0;}GameContext g(CharacterClass::IRONCLAD,123,20);g.act=q.value("act",1);g.floorNum=q.value("floor",6);g.curHp=q.value("hp",40);g.maxHp=q.value("max_hp",80);g.gold=q.value("gold",1000);
 g.curRoom=q.value("room",std::string("EVENT"))=="SHOP"?Room::SHOP:Room::EVENT;g.screenState=ScreenState::MAP_SCREEN;g.regainControlAction=[](GameContext&a){a.screenState=ScreenState::MAP_SCREEN;};
 g.miscRng=Random(q.value("misc_seed",0));g.cardRng=Random(123);g.cardRandomRng=Random(123);g.potionRng=Random(123);g.relicRng=Random(123);g.merchantRng=Random(123);g.cardRarityFactor=5;g.shuffleRng=Random(123);
 if(q.contains("pools")){auto&p=q["pools"];if(p.contains("colorless"))g.colorlessCardPool=p["colorless"].get<std::array<CardId,35>>();g.commonRelicPool=p["common"].get<std::vector<RelicId>>();g.uncommonRelicPool=p["uncommon"].get<std::vector<RelicId>>();g.rareRelicPool=p["rare"].get<std::vector<RelicId>>();g.shopRelicPool=p["shop"].get<std::vector<RelicId>>();g.bossRelicPool=p["boss"].get<std::vector<RelicId>>();}
 if(q.contains("deck")){g.deck=Deck();for(auto c:q["deck"]){g.deck.obtainRaw(parseCard(c));if(c.is_object()&&c.value("bottled",false))g.deck.bottleCard(g.deck.size()-1,g.deck.cards.back().getType());}}
 if(q.contains("initial_potions")){g.potionCapacity=q["initial_potions"].size();g.potionCount=0;for(int i=0;i<g.potionCapacity;i++){g.potions[i]=q["initial_potions"][i].get<Potion>();if(g.potions[i]!=Potion::EMPTY_POTION_SLOT)++g.potionCount;}}
 if(q.contains("initial_relics")){g.relics=RelicContainer{};for(auto r:q["initial_relics"])g.relics.add({r.at("id").get<RelicId>(),r.at("counter").get<int>()});}
 else if(q.value("drop_starter",false))g.loseRelic(RelicId::BURNING_BLOOD);
 if(!q.contains("initial_relics")&&q.contains("relics"))for(auto r:q["relics"]){auto id=(r.is_string()?r:r["id"]).get<RelicId>();g.relics.add({id,r.is_string()?0:r.value("counter",0)});}
 if(q.value("kind",std::string("event"))=="event") {g.curEvent=q.at("id").get<Event>();if(g.curEvent==Event::INVALID)throw std::runtime_error("unknown event");g.setupEvent();for(int i:q.value("sim_choices",q.value("choices",json::array()))){GA(i).execute(g);if(g.screenState==ScreenState::BATTLE)break;}}
 else if(q["kind"]=="relic")g.obtainRelic(q.at("id").get<RelicId>());
 else if(q["kind"]=="pool"){auto r=g.returnRandomRelic(static_cast<RelicTier>(q.at("tier").get<int>()));g.obtainRelic(r);}
 json stock=nullptr;
 if(q["kind"]=="shop_card"||q["kind"]=="shop_potion"){
  g.curRoom=Room::SHOP;g.screenState=ScreenState::SHOP_ROOM;auto &shop=g.info.shop;for(auto &price:shop.prices)price=-1;
  stock=json::object();
  if(q["kind"]=="shop_card"){
   Card c(q.at("card").get<CardId>());const int idx=getCardColor(c.id)==CardColor::COLORLESS?5:0;shop.cards[idx]=c;shop.cardPrice(idx)=q.value("price",50);g.mathUtilRng=Random(123);shop.buyCard(g,idx);
   if(shop.cardPrice(idx)!=-1)stock={{"card",card(shop.cards[idx])},{"price",shop.cardPrice(idx)}};
  }else{
   shop.potions[0]=q.at("potion").get<Potion>();shop.potionPrice(0)=q.value("price",50);shop.buyPotion(g,0);
   if(shop.potionPrice(0)!=-1)stock={{"potion",shop.potions[0]},{"price",shop.potionPrice(0)}};
  }
 }
 if(q.contains("sim_select")){for(int i:q["sim_select"]){if(g.screenState!=ScreenState::CARD_SELECT)throw std::runtime_error("selection is not open");GA(i).execute(g);}}
 if(q.contains("select_ids"))for(auto id:q["select_ids"]){auto cardId=id.get<CardId>();int idx=-1;for(int i=0;i<g.info.toSelectCards.size();i++)if(g.info.toSelectCards[i].card.id==cardId){idx=i;break;}if(idx<0)throw std::runtime_error("selected card not offered");GA(idx).execute(g);}
 std::unique_ptr<BattleContext> battle;
 for(auto op:q.value("ops",json::array())){
  if(op.contains("drink"))g.drinkPotionAtIdx(op["drink"]);
  if(op.contains("heal")){if(!battle)throw std::runtime_error("heal needs a battle");battle->player.heal(op["heal"]);}
  if(op.contains("victory")){if(!battle)throw std::runtime_error("victory needs a battle");battle->outcome=Outcome::PLAYER_VICTORY;battle->exitBattle(g);}
  if(op.contains("event_rewards")){if(g.screenState!=ScreenState::BATTLE)throw std::runtime_error("event did not enter combat");g.afterBattle();}
  if(op.contains("room")){Room room=op["room"]=="REST"?Room::REST:(op["room"]=="SHOP"?Room::SHOP:Room::EVENT);g.lastRoom=g.curRoom;g.curRoom=room;g.relicsOnEnterRoom(room);if(room==Room::SHOP&&g.hasRelic(RelicId::MEAL_TICKET))g.playerHeal(15);}
  if(op.contains("spend"))g.loseGold(op["spend"],true);
  if(op.contains("card"))g.deck.obtain(g,parseCard(op["card"]));
  if(op.contains("remove")){auto id=op["remove"].get<CardId>();for(int i=0;i<g.deck.size();i++)if(g.deck.cards[i].id==id){g.deck.remove(g,i);break;}}
  if(op.contains("acquire"))g.obtainRelic(op["acquire"].get<RelicId>());
  if(op.contains("battle")){g.regainControlAction=[](GameContext&a){a.afterBattle();};g.curRoom=Room::MONSTER;g.screenState=ScreenState::BATTLE;g.info.encounter=MonsterEncounter::CULTIST;battle=std::make_unique<BattleContext>();battle->init(g);}
 }
 auto out=snapshot(g);if(!stock.is_null())out["stock"]=stock;if(q.value("legal_event",false)){out["legal_event"]=json::array();for(auto a:GA::getAllActionsInState(g))if(!a.isPotionAction())out["legal_event"].push_back(a.getIdx1());}if(q.value("kind",std::string("event"))=="eligibility")for(auto id:q["ids"])out["eligibility"][id.get<std::string>()]=g.relicCanSpawn(id.get<RelicId>(),g.curRoom==Room::SHOP);if(battle){out["combat"]={{"energy",battle->player.energy},{"strength",battle->player.getStatus<PlayerStatus::STRENGTH>()},{"block",battle->player.block}};if(q.value("battle_detail",false)){out["hp"]=battle->player.curHp;out["gold"]=battle->player.gold;for(auto entry:std::initializer_list<std::pair<const char*,const Random*>>{{"shuffleRng",&battle->shuffleRng},{"cardRandomRng",&battle->cardRandomRng}}){auto&r=*entry.second;out["rng"][entry.first]={{"counter",r.counter},{"seed0",r.seed0},{"seed1",r.seed1}};}auto&p=battle->player;out["combat"]["powers"]={{"Strength",p.getStatus<PlayerStatus::STRENGTH>()},{"Dexterity",p.getStatus<PlayerStatus::DEXTERITY>()},{"Weakened",p.getStatus<PlayerStatus::WEAK>()},{"Artifact",p.getStatus<PlayerStatus::ARTIFACT>()},{"Vigor",p.getStatus<PlayerStatus::VIGOR>()},{"Buffer",p.getStatus<PlayerStatus::BUFFER>()},{"Plated Armor",p.getStatus<PlayerStatus::PLATED_ARMOR>()},{"IntangiblePlayer",p.getStatus<PlayerStatus::INTANGIBLE>()},{"Next Turn Block",p.getStatus<PlayerStatus::NEXT_TURN_BLOCK>()},{"Metallicize",p.getStatus<PlayerStatus::METALLICIZE>()},{"Draw Card",p.getStatus<PlayerStatus::DRAW_CARD_NEXT_TURN>()}};auto&hand=out["combat"]["hand"]=json::array();for(int i=0;i<battle->cards.cardsInHand;i++){auto&c=battle->cards.hand[i];hand.push_back({{"id",c.getId()},{"upgrades",c.isUpgraded()?1:0},{"misc",c.getId()==CardId::RITUAL_DAGGER?c.specialData:0},{"bottled",false}});}}}
 std::cout<<out.dump()<<'\n';
 }catch(const std::exception&e){std::cout<<json({{"error",e.what()}}).dump()<<'\n';return 1;}}
