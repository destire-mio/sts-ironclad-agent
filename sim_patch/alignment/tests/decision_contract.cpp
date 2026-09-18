#include "game/GameContext.h"
#include "sim/search/GameAction.h"
#include "sim/search/SimpleAgent.h"
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <set>
using namespace sts;
using GA=sts::search::GameAction;
using RT=GA::RewardsActionType;
void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
bool offered(const GameContext&g,GA a){for(auto v:GA::getAllActionsInState(g))if(v.bits==a.bits)return true;return false;}
void valid(const GameContext&g){std::set<unsigned>seen;for(auto a:GA::getAllActionsInState(g)){check(a.isValidAction(g),"enumerated action is illegal");check(seen.insert(a.bits).second,"duplicate action");}}
GameContext game(){GameContext g(CharacterClass::IRONCLAD,123,20);g.curHp=40;g.maxHp=80;g.gold=200;g.screenState=ScreenState::MAP_SCREEN;g.regainControlAction=[](GameContext&n){n.screenState=ScreenState::MAP_SCREEN;};return g;}
void shop(GameContext&g){g.curRoom=Room::SHOP;g.screenState=ScreenState::SHOP_ROOM;for(auto&p:g.info.shop.prices)p=-1;g.info.shop.removeCost=75;}
int main(int argc,char**argv){try{const std::string mode=argv[1];auto g=game();
 if(mode=="reward_choices"){
  Rewards pending;CardReward offer;offer.push_back(CardId::ANGER);pending.addCardReward(offer);pending.addCardReward(offer);g.openCombatRewardScreen(pending);
  check(!offered(g,GA(RT::CARD,0,5))&&!GA(RT::CARD,0,5).isValidAction(g),"card-screen skip must not delete an unclaimed offer without Singing Bowl");
  GA(RT::CARD,1,0).execute(g);check(g.info.rewardsContainer.cardRewardCount==1,"choosing a later offer deleted an earlier offer");
  GA(RT::SKIP).execute(g);check(g.screenState==ScreenState::MAP_SCREEN,"declining remaining rewards did not leave");g=game();
  g.obtainRelic(RelicId::SINGING_BOWL);Rewards rewards;CardReward cards;cards.push_back(CardId::ANGER);rewards.addCardReward(cards);rewards.addCardReward(cards);g.openCombatRewardScreen(rewards);
  check(offered(g,GA(RT::CARD,0,5))&&offered(g,GA(RT::CARD,1,5)),"Singing Bowl missing from candidates");valid(g);
  GA(RT::CARD,0,5).execute(g);check(g.maxHp==82&&g.curHp==42&&g.info.rewardsContainer.cardRewardCount==1,"Bowl did not claim just one offer");GA(RT::CARD,0,0).execute(g);check(g.deck.cards.back().id==CardId::ANGER&&g.info.rewardsContainer.cardRewardCount==0,"remaining reward was lost");
 }else if(mode=="simple_reward_child"){
  Rewards pending;pending.addRelic(RelicId::BOTTLED_FLAME);CardReward offer;offer.push_back(CardId::ANGER);pending.addCardReward(offer);g.openCombatRewardScreen(pending);
  search::SimpleAgent agent;agent.stepRewardsScreen(g);check(g.screenState==ScreenState::CARD_SELECT&&g.deck.bottleIdxs[0]==-1,"simple policy consumed card reward while bottle selection was open");
  GA(0).execute(g);check(g.screenState==ScreenState::REWARDS&&g.info.rewardsContainer.cardRewardCount==1,"bottle child lost remaining card offer");
 }else if(mode=="potion_choices"){
  g.obtainPotion(Potion::FIRE_POTION);g.obtainPotion(Potion::BLOOD_POTION);const GA drink(0x80000001U),discard(0xC0000000U);valid(g);check(offered(g,drink)&&offered(g,discard)&&!offered(g,GA(0x80000000U)),"outside potion action set is wrong");
  auto branch=g;drink.execute(branch);check(branch.curHp==56&&branch.potionCount==1&&g.curHp==40&&g.potionCount==2,"potion choice mutated sibling candidate");discard.execute(g);Rewards r;r.addPotion(Potion::FRUIT_JUICE);g.openCombatRewardScreen(r);GA(RT::POTION,0).execute(g);check(g.potions[0]==Potion::FRUIT_JUICE&&g.potionCount==2,"freed slot could not claim a reward");
  g.screenState=ScreenState::BATTLE;check(GA::getAllActionsInState(g).empty(),"game actions leaked into combat");
 }else if(mode=="sozu_shop"){
  g.obtainRelic(RelicId::SOZU);g.obtainRelic(RelicId::THE_COURIER);shop(g);g.info.shop.potions[0]=Potion::FIRE_POTION;g.info.shop.potionPrice(0)=50;auto rng=g.potionRng;check(!offered(g,GA(RT::POTION,0))&&!GA(RT::POTION,0).isValidAction(g),"Sozu can purchase potions");g.info.shop.buyPotion(g,0);check(g.gold==200&&g.potionCount==0&&g.info.shop.potionPrice(0)==50&&g.potionRng.counter==rng.counter,"Sozu purchase spent money or RNG");
  g.potionCount=g.potionCapacity;Rewards r;r.addPotion(Potion::FIRE_POTION);g.openCombatRewardScreen(r);check(offered(g,GA(RT::POTION,0)),"Sozu cannot dismiss potion reward");GA(RT::POTION,0).execute(g);check(g.info.rewardsContainer.potionCount==0&&g.potionCount==g.potionCapacity,"Sozu reward changed inventory");
 }else if(mode=="shop_cancel"){
  shop(g);g.obtainRelic(RelicId::MAW_BANK);const auto size=g.deck.size();GA(RT::CARD_REMOVE).execute(g);check(g.gold==200&&g.shopRemoveCount==0&&g.relics.getRelicValue(RelicId::MAW_BANK)==-1,"opening purge charged money");valid(g);check(offered(g,GA(RT::SKIP)),"purge cancel missing");auto sibling=g;GA(RT::SKIP).execute(g);check(g.screenState==ScreenState::SHOP_ROOM&&g.gold==200&&g.deck.size()==size&&g.info.shop.removeCost==75,"cancel lost shop state");GA(0).execute(sibling);check(sibling.screenState==ScreenState::SHOP_ROOM&&sibling.gold==125&&sibling.deck.size()==size-1&&sibling.shopRemoveCount==1&&sibling.info.shop.removeCost==-1,"confirmed purge not settled");check(g.gold==200&&g.deck.size()==size,"purge branch mutated sibling");GA(RT::SKIP).execute(sibling);check(sibling.screenState==ScreenState::MAP_SCREEN,"shop continuation lost after purge");
 }else if(mode=="rest_cancel"){
  g.curRoom=Room::REST;g.screenState=ScreenState::REST_ROOM;g.obtainRelic(RelicId::PEACE_PIPE);const auto size=g.deck.size();for(int choice:{1,4}){GA(choice).execute(g);valid(g);check(offered(g,GA(RT::SKIP)),"campfire cancel missing");GA(RT::SKIP).execute(g);check(g.screenState==ScreenState::REST_ROOM&&g.curHp==40&&g.deck.size()==size,"cancel consumed campfire");}GA(2).execute(g);check(g.redKey&&g.screenState==ScreenState::MAP_SCREEN,"recall after cancellation failed");
 }else throw std::runtime_error("unknown test");
 std::cout<<mode<<" passed\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
