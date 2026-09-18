#include "game/GameContext.h"
#include "game/Game.h"
#include "game/SaveFile.h"
#include "combat/BattleContext.h"
#include "sim/search/GameAction.h"
#include <iostream>
#include <stdexcept>
using namespace sts;
using GA=search::GameAction;
using RT=GA::RewardsActionType;
void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
GameContext game(){GameContext g(CharacterClass::IRONCLAD,123,20);g.gold=1000;g.curHp=40;g.maxHp=80;g.regainControlAction=[](GameContext&a){a.screenState=ScreenState::MAP_SCREEN;};return g;}
int count(const GameContext&g,CardId id){return g.deck.getCountMatching([=](const Card&c){return c.id==id;});}
void event(GameContext&g,Event e,int choice){g.curEvent=e;g.curRoom=Room::EVENT;g.setupEvent();GA(choice).execute(g);}
void shop(GameContext&g){g.curRoom=Room::SHOP;g.screenState=ScreenState::SHOP_ROOM;g.info.shop.setup(g);}
void buy(GameContext&g,RelicId id,int price=200){shop(g);g.info.shop.relics[0]=id;g.info.shop.relicPrice(0)=price;GA(RT::RELIC,0).execute(g);}
void chest(GameContext&g){g.curRoom=Room::TREASURE;g.info.tier=RelicTier::COMMON;g.info.haveGold=false;g.screenState=ScreenState::TREASURE_ROOM;GA(0).execute(g);}
void trade(GameContext&g,int relicIndex){g.curRoom=Room::EVENT;g.curEvent=Event::NLOTH;g.setupEvent();g.info.relicIdx0=relicIndex;GA(0).execute(g);}
int main(int argc,char**argv){try{
 const std::string mode=argv[1];auto g=game();
 if(mode=="F01"){
  g.obtainRelic(RelicId::THE_COURIER);g.merchantRng=Random(123);check(Shop::getNewPrice(g,50)==41,"native potion price fixture differs");
  for(bool member:{false,true}){
   auto a=game();a.obtainRelic(RelicId::THE_COURIER);if(member)a.obtainRelic(RelicId::MEMBERSHIP_CARD);shop(a);auto&s=a.info.shop;
   s.buyPotion(a,0);check(s.potionPrice(0)>1,"Courier potion restock discarded base price");
   auto rng=a.merchantRng;rng.random(99);float roll=rng.random(.95f,1.05f);s.relics[0]=RelicId::VAJRA;s.relicPrice(0)=111;
   s.buyRelic(a,0);int expected=std::round(getRelicBasePrice(s.relics[0])*roll);expected=std::round(expected*.8f);if(member)expected=std::round(expected*.5f);
   check(s.relicPrice(0)==expected,"Courier relic restock did not write original price formula");
   for(int base:{50,75,100,150,250,300}){auto before=a.merchantRng;int price=std::round(base*before.random(.95f,1.05f));price=std::round(price*.8f);if(member)price=std::round(price*.5f);check(Shop::getNewPrice(a,base)==price,"restock sequential rounding differs");}
  }
 }
 else if(mode=="F02"){
  g.obtainRelic(RelicId::LIZARD_TAIL);g.curHp=1;g.playerLoseHp(2);check(g.curHp==40&&g.outcome==GameOutcome::UNDECIDED,"new tail did not revive outside combat");g.playerLoseHp(41);check(g.outcome==GameOutcome::PLAYER_LOSS,"tail revived twice");
  for(int counter:{-1,-2}){auto a=game();SaveFile s;s.relics={RelicId::LIZARD_TAIL};s.relic_counters={counter};a.initRelicsFromSave(s);a.curHp=1;BattleContext b;b.init(a,MonsterEncounter::CULTIST);b.player.loseHp(b,2,true);check((b.player.curHp>0)==(counter==-1),"saved tail availability differs in combat");if(counter==-1){b.outcome=Outcome::PLAYER_ESCAPE;b.exitBattle(a);check(a.relics.getRelicValue(RelicId::LIZARD_TAIL)==-2,"tail consumption not written back");BattleContext next;next.init(a,MonsterEncounter::CULTIST);check(!next.player.hasRelic<RelicId::LIZARD_TAIL>(),"consumed tail returned next battle");}}
  auto a=game();a.obtainRelic(RelicId::LIZARD_TAIL);a.obtainRelic(RelicId::MARK_OF_THE_BLOOM);a.curHp=1;a.playerLoseHp(2);check(a.outcome==GameOutcome::PLAYER_LOSS,"Bloom failed to block tail");
 }
 else if(mode=="F03"){
  const int gold=g.gold;event(g,Event::HYPNOTIZING_COLORED_MUSHROOMS,1);check(g.curHp==60&&g.gold==gold&&count(g,CardId::PARASITE)==1,"Mushrooms eat reward differs");
  auto a=game();a.obtainRelic(RelicId::OMAMORI);a.obtainRelic(RelicId::MARK_OF_THE_BLOOM);event(a,Event::HYPNOTIZING_COLORED_MUSHROOMS,1);check(a.curHp==40&&count(a,CardId::PARASITE)==0&&a.relics.getRelicValue(RelicId::OMAMORI)==1,"Mushrooms ignored Bloom/Omamori");
 }
 else if(mode=="F04"){
  for(int i=0;i<3;i++){auto a=game();event(a,Event::THE_WOMAN_IN_BLUE,i);check(a.gold==980-10*i&&a.info.rewardsContainer.potionCount==i+1,"Woman failed to charge potion bundle");}
  event(g,Event::THE_WOMAN_IN_BLUE,3);check(g.curHp==36&&g.gold==1000,"Woman leave changed purchase behavior");
 }
 else if(mode=="F05"){
  g.obtainRelic(RelicId::NECRONOMICON);check(count(g,CardId::NECRONOMICURSE)==1,"Necronomicon omitted curse");trade(g,1);check(count(g,CardId::NECRONOMICURSE)==0,"Necronomicon curse survived unequip");
  auto a=game();a.obtainRelic(RelicId::OMAMORI);a.obtainRelic(RelicId::NECRONOMICON);check(count(a,CardId::NECRONOMICURSE)==0&&a.relics.getRelicValue(RelicId::OMAMORI)==1,"Necronomicon bypassed curse prevention");
 }
 else if(mode=="F06"){
  g.deck=Deck();g.deck.obtainRaw(Card(CardId::SEARING_BLOW,4));Card dagger(CardId::RITUAL_DAGGER,1);dagger.misc=39;g.deck.obtainRaw(dagger);g.deck.obtainRaw(CardId::ASCENDERS_BANE);g.deck.bottleCard(0,CardType::ATTACK);
  buy(g,RelicId::DOLLYS_MIRROR);check(g.screenState==ScreenState::CARD_SELECT&&g.gold==800,"Mirror failed to open selection");
  auto copy=g;GA(0).execute(copy);check(copy.deck.size()==4&&copy.deck.cards[3].getUpgraded()==4&&copy.deck.bottleIdxs[0]==0&&!copy.deck.isCardBottled(3),"Mirror lost repeated upgrades or copied bottle");
  GA(1).execute(g);check(g.deck.size()==4&&g.deck.cards[3].misc==39&&g.deck.cards[3].getUpgraded()==1&&g.screenState==ScreenState::SHOP_ROOM,"Mirror lost special value or shop continuation");
 }
 else if(mode=="F07"){
  buy(g,RelicId::ORRERY);check(g.screenState==ScreenState::REWARDS&&g.info.rewardsContainer.cardRewardCount==5,"Orrery omitted five card rewards");int size=g.deck.size();for(int i=0;i<5;i++)GA(RT::CARD,0,0).execute(g);check(g.deck.size()==size+5,"Orrery could not claim all rewards");GA(RT::SKIP).execute(g);check(g.screenState==ScreenState::SHOP_ROOM,"Orrery did not return to shop");
  // Original v2.3.4 Orrery in ShopRoom, card RNG seed 123, rarity offset 5.
  auto a=game();shop(a);a.cardRng=Random(123);a.cardRarityFactor=5;a.info.shop.relics[0]=RelicId::ORRERY;a.info.shop.relicPrice(0)=200;GA(RT::RELIC,0).execute(a);
  CardId offers[5][3]={{CardId::BODY_SLAM,CardId::BATTLE_TRANCE,CardId::HEADBUTT},{CardId::PUMMEL,CardId::TWIN_STRIKE,CardId::WILD_STRIKE},{CardId::FIRE_BREATHING,CardId::WARCRY,CardId::CLEAVE},{CardId::CLOTHESLINE,CardId::INFLAME,CardId::ARMAMENTS},{CardId::POWER_THROUGH,CardId::BARRICADE,CardId::ARMAMENTS}};
  for(int i=0;i<5;i++)for(int j=0;j<3;j++){auto c=a.info.rewardsContainer.cardRewards[i][j];check(c.id==offers[i][j]&&c.getUpgraded()==0,"Orrery offers differ from original shop rarity/RNG");}
  check(a.cardRng.counter==44&&a.cardRarityFactor==4,"Orrery continuation RNG differs from original");
 }
 else if(mode=="F08"){
  g.obtainRelic(RelicId::WING_BOOTS);check(g.relics.getRelicValue(RelicId::WING_BOOTS)==3,"Wing Boots missing charges");g.map=std::make_shared<Map>();
  for(int y=0;y<15;y++)for(int x=0;x<7;x++){auto&n=g.map->nodes[y][x];n.x=x;n.y=y;if(x<2){n.room=Room::REST;n.edgeCount=1;n.edges[0]=x;}}
  g.curMapNodeY=0;g.curMapNodeX=0;
  for(int i=0;i<3;i++){g.screenState=ScreenState::MAP_SCREEN;int target=1-g.curMapNodeX;check(GA(target).isValidAction(g),"Wing Boots legal crossing missing");auto actions=GA::getAllActionsInState(g);bool found=false;for(auto a:actions)found|=a.getIdx1()==target;check(found,"Wing Boots crossing missing from candidates");check(!GA(6).isValidAction(g),"Wing Boots allowed empty node");auto branch=g;GA(target).execute(branch);check(g.relics.getRelicValue(RelicId::WING_BOOTS)==3-i,"Wing Boots branch mutated parent");g=branch;}
  g.screenState=ScreenState::MAP_SCREEN;check(g.relics.getRelicValue(RelicId::WING_BOOTS)==-2&&!GA(1-g.curMapNodeX).isValidAction(g),"Wing Boots did not exhaust after three crossings");GA(g.curMapNodeX).execute(g);check(g.relics.getRelicValue(RelicId::WING_BOOTS)==-2,"normal route consumed charge");
 }
 else if(mode=="F09"){
  g.obtainRelic(RelicId::GOLDEN_IDOL);event(g,Event::FORGOTTEN_ALTAR,0);check(g.relics.relics[1].id==RelicId::BLOODY_IDOL&&!g.hasRelic(RelicId::GOLDEN_IDOL),"Altar relic list and flags disagree");trade(g,1);int hp=g.curHp;g.obtainGold(10);check(!g.hasRelic(RelicId::BLOODY_IDOL)&&g.curHp==hp,"traded Bloody Idol still heals");
 }
 else if(mode=="F10"){
  g.obtainRelic(RelicId::OLD_COIN);check(g.gold==1300,"Old Coin did not grant 300 gold");auto a=game();a.obtainRelic(RelicId::ECTOPLASM);a.obtainRelic(RelicId::OLD_COIN);check(a.gold==1000,"Old Coin bypassed Ectoplasm");
 }
 else if(mode=="F11"){
  g.obtainRelic(RelicId::MATRYOSHKA);for(int i=0;i<3;i++){chest(g);check(g.info.rewardsContainer.relicCount==(i<2?2:1),"Matryoshka chest rewards differ");}check(g.relics.getRelicValue(RelicId::MATRYOSHKA)==-2,"Matryoshka depleted counter differs");
 }
 else if(mode=="F12"){
  g.obtainRelic(RelicId::NLOTHS_HUNGRY_FACE);chest(g);check(g.info.rewardsContainer.relicCount==0&&!g.info.rewardsContainer.sapphireKey,"Hungry Face failed to remove linked relic/key");chest(g);check(g.info.rewardsContainer.relicCount==1,"Hungry Face consumed a second chest");
  auto a=game();a.obtainRelic(RelicId::MATRYOSHKA);a.obtainRelic(RelicId::NLOTHS_HUNGRY_FACE);auto expected=a;expected.relics.remove(RelicId::NLOTHS_HUNGRY_FACE);chest(expected);auto base=expected.info.rewardsContainer.relics[1];chest(a);check(a.info.rewardsContainer.relicCount==1&&a.info.rewardsContainer.relics[0]==base&&a.info.rewardsContainer.sapphireKey,"Hungry Face removed wrong Matryoshka relic or key");
 }
 else if(mode=="F13"){
  event(g,Event::MYSTERIOUS_SPHERE,1);check(g.gold==1000&&g.curHp==40&&g.deck.size()==11,"Sphere leave granted resources");
 }
 else if(mode=="F14"){
  event(g,Event::THE_MAUSOLEUM,0);check(g.relics.size()==2&&count(g,CardId::WRITHE)==1,"Mausoleum omitted relic/curse");auto a=game();event(a,Event::THE_MAUSOLEUM,1);check(a.relics.size()==1&&a.deck.size()==11,"Mausoleum leave granted rewards");
 }
 else if(mode=="F15"){
  g.miscRng=Random(0);g.curHp=80;g.curRoom=Room::EVENT;g.curEvent=Event::SCRAP_OOZE;g.setupEvent();GA(0).execute(g);check(g.curHp==75&&g.screenState==ScreenState::EVENT_SCREEN,"Scrap fixture did not fail first attempt");GA(0).execute(g);check(g.curHp==69,"Scrap second damage was not six");
 }
 else if(mode=="F16"){
  g.obtainRelic(RelicId::THE_COURIER);g.merchantRng=Random(123);check(Shop::getNewCardPrice(g,CardRarity::COMMON,false)==42,"native card price fixture differs");
  for(bool courier:{false,true})for(bool member:{false,true}){auto a=game();if(courier)a.obtainRelic(RelicId::THE_COURIER);if(member)a.obtainRelic(RelicId::MEMBERSHIP_CARD);auto rng=a.merchantRng;float p=50*rng.random(.9f,1.1f);if(courier)p*=.8f;if(member)p*=.5f;check(Shop::getNewCardPrice(a,CardRarity::COMMON,false)==(int)p,"restocked card discount differs");}
 }
 else if(mode=="F17"){
  g.obtainRelic(RelicId::SMILING_MASK);g.obtainRelic(RelicId::THE_COURIER);g.obtainRelic(RelicId::MEMBERSHIP_CARD);shop(g);check(g.info.shop.removeCost==50,"Mask combined price not fifty");auto a=game();a.obtainRelic(RelicId::SMILING_MASK);buy(a,RelicId::MEMBERSHIP_CARD);check(a.info.shop.removeCost==50,"buying Membership discounted Mask");
  auto b=game();b.obtainRelic(RelicId::THE_COURIER);buy(b,RelicId::MEMBERSHIP_CARD);check(b.info.shop.removeCost==38,"Membership purchase stacked purge discounts");shop(b);check(b.info.shop.removeCost==38,"shop entry stacked purge discounts");
 }
 else if(mode=="F18"){
  for(auto type:{CardType::ATTACK,CardType::SKILL,CardType::POWER}){auto a=game();const int t=(int)type;RelicId relics[]={RelicId::BOTTLED_FLAME,RelicId::BOTTLED_LIGHTNING,RelicId::BOTTLED_TORNADO};CardId cards[]={CardId::BASH,CardId::DEFEND_RED,CardId::INFLAME};a.deck=Deck();a.deck.obtainRaw(cards[t]);a.deck.obtainRaw(CardId::ASCENDERS_BANE);a.obtainRelic(relics[t]);GA(0).execute(a);trade(a,1);check(!a.deck.isCardBottled(0)&&a.deck.getTransformableCount()==1,"bottle state or removal count survived trade");BattleContext b;b.init(a,MonsterEncounter::CULTIST);check(!a.hasRelic(relics[t]),"traded bottle remained owned");}
 }
 else throw std::runtime_error("unknown review case");
 std::cout<<"PASS "<<mode<<'\n';
 }catch(const std::exception&e){std::cerr<<"FAIL "<<argv[1]<<": "<<e.what()<<'\n';return 1;}}
