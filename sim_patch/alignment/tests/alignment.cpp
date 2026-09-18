#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "combat/Actions.h"
#include "sim/search/Action.h"
#include "sim/search/GameAction.h"
#include "sim/search/BattleScumSearcher2.h"
#include "sim/search/ScumSearchAgent2.h"
#include "sim/ConsoleSimulator.h"
#include "slaythespire.h"
#include "constants/SaveFileMappings.h"
#include <iostream>
#include <stdexcept>
#include <set>
#include <sstream>
using namespace sts;
void check(bool value,const char* message) { if(!value) throw std::runtime_error(message); }
bool offered(const GameContext &g,const search::GameAction &wanted) {for(const auto action:search::GameAction::getAllActionsInState(g))if(action.bits==wanted.bits)return true;return false;}
void consistent(const Deck& d) {
    std::array<int,4> types{}; int upgrades=0,transforms=0;
    for(int i=0;i<d.size();++i) {const auto& c=d.cards[i];++types[static_cast<int>(c.getType())];upgrades+=c.canUpgrade();transforms+=c.canTransform()&&!d.isCardBottled(i);}
    check(d.cardTypeCounts==types,"deck type counters disagree with cards");
    check(d.getUpgradeableCount()==upgrades,"upgradeable count disagrees with cards");
    check(d.getTransformableCount()==transforms,"transformable count disagrees with cards");
}
GameContext game() {return GameContext(CharacterClass::IRONCLAD,123,20);}
void add(BattleContext& b,CardId id) {CardInstance c(id);c.uniqueId=b.cards.nextUniqueCardId++;b.cards.notifyAddCardToCombat(c);b.cards.notifyAddToHand(c);b.cards.hand[b.cards.cardsInHand++]=c;}
void addDrawTop(BattleContext& b,CardId id) {CardInstance c(id);c.uniqueId=b.cards.nextUniqueCardId++;b.cards.notifyAddCardToCombat(c);b.cards.notifyAddToDrawPile(c);b.cards.drawPile.push_back(c);}
int main(int argc,char**argv) {try {
    const std::string mode=argv[1];auto g=game();
    if(mode=="book_stab_count") {
        bool sawSingle=false,sawMulti=false;
        for(int seed=1;seed<=24;++seed) {
            GameContext a(CharacterClass::IRONCLAD,seed,20);a.act=2;a.curRoom=Room::ELITE;a.info.encounter=MonsterEncounter::BOOK_OF_STABBING;
            BattleContext b;b.init(a);const auto&m=b.monsters.arr[0];
            check(m.miscInfo==2,"Book prebattle incremented stabCount after first intent rolled");
            if(m.moveHistory[0]==MonsterMoveId::BOOK_OF_STABBING_MULTI_STAB){sawMulti=true;check(m.getMoveBaseDamage(b).attackCount==2,"Book opening multi-stab count wrong");}
            else sawSingle=true;
        }
        check(sawSingle&&sawMulti,"Book test did not exercise both opening moves");
    }
    else if(mode=="emerald_elite_buffs") {
        for(int act:{1,2,3})for(int buff:{0,1,2,3}) {
            auto a=game();a.act=act;a.curRoom=Room::ELITE;a.info.encounter=MonsterEncounter::GREMLIN_NOB;
            a.curMapNodeX=0;a.curMapNodeY=0;a.map->burningEliteX=-1;
            BattleContext normal;normal.init(a);
            a.map->burningEliteX=0;a.map->burningEliteY=0;a.map->burningEliteBuff=buff;
            BattleContext empowered;empowered.init(a);
            const auto &n=normal.monsters.arr[0],&m=empowered.monsters.arr[0];
            check(m.strength==n.strength+(buff==0?act+1:0),"emerald elite Strength differs from original act + 1");
            const int extra=buff==1?static_cast<int>(std::round(n.maxHp*.25f)):0;
            check(m.maxHp==n.maxHp+extra&&m.curHp==n.curHp+extra,"emerald elite HP rounding differs");
            check(m.getStatus<MonsterStatus::METALLICIZE>()==(buff==2?act*2+2:0),"emerald elite metallicize differs");
            check(m.getStatus<MonsterStatus::REGEN>()==(buff==3?act*2+1:0),"emerald elite regeneration differs");
        }
    }
    else if(mode=="potion_discard_description") {
        g.info.encounter=MonsterEncounter::CULTIST;BattleContext b;b.init(g);b.potions[0]=Potion::FIRE_POTION;b.potionCount=1;
        for(int target:{-1,6,15}) {
            search::Action action(search::ActionType::POTION,0,target);check(action.isValidAction(b),"discard not legal");
            std::ostringstream description;action.printDesc(description,b);
            check(description.str().find("discard potion")!=std::string::npos&&description.str().find("->")==std::string::npos,"discard treated encoded sentinel as monster index");
        }
        search::Action action(search::ActionType::POTION,0,0);std::ostringstream description;action.printDesc(description,b);check(description.str().find("drink potion")!=std::string::npos&&description.str().find("->")!=std::string::npos,"targeted potion description lost target");
    }
    else if(mode=="deck_raw_counts") {g.deck=Deck();g.deck.obtainRaw(CardId::STRIKE_RED);g.deck.obtainRaw(CardId::ASCENDERS_BANE);g.deck.obtainRaw(CardId::REGRET);consistent(g.deck);}
    else if(mode=="curse_event") {
        g.deck=Deck();
        for(auto id:{CardId::ASCENDERS_BANE,CardId::NECRONOMICURSE,CardId::CURSE_OF_THE_BELL})g.deck.obtainRaw(id);
        check(!g.canAddOneTimeEvent(Event::THE_DIVINE_FOUNTAIN),"permanent curses admitted Fountain of Cleansing");
        consistent(g.deck);
        g.deck.obtainRaw(CardId::REGRET);
        check(g.canAddOneTimeEvent(Event::THE_DIVINE_FOUNTAIN),"removable curse did not admit Fountain of Cleansing");
        g.deck.remove(g,3);
        check(!g.canAddOneTimeEvent(Event::THE_DIVINE_FOUNTAIN),"Fountain remained after removable curse removal");
        consistent(g.deck);
    }
    else if(mode=="lab_rewards") {
        for(int ascension:{14,20}) {
            auto a=game();a.ascension=ascension;a.curEvent=Event::LAB;
            const auto counter=a.potionRng.counter;a.setupEvent();
            check(a.screenState==ScreenState::EVENT_SCREEN && a.potionRng.counter==counter,"Lab generated rewards before Search");
            search::GameAction(0).execute(a);
            check(a.screenState==ScreenState::REWARDS && a.info.rewardsContainer.potionCount==(ascension==20?2:3),"Lab search rewards wrong");
        }
    }
    else if(mode=="bottle_reward_return") {
        g.regainControlAction=[](GameContext &a){a.screenState=ScreenState::MAP_SCREEN;};
        Rewards rewards;rewards.addRelic(RelicId::BOTTLED_FLAME);rewards.addGold(29);CardReward cards;cards.push_back(CardId::FEEL_NO_PAIN);rewards.addCardReward(cards);g.openCombatRewardScreen(rewards);
        using Type=search::GameAction::RewardsActionType;
        search::GameAction(Type::RELIC,0).execute(g);
        check(g.screenState==ScreenState::CARD_SELECT,"bottle did not request a card");
        auto branch=g;search::GameAction(0).execute(branch);
        check(g.deck.bottleIdxs[0]==-1 && g.screenState==ScreenState::CARD_SELECT,"bottle branch changed its parent");
        check(branch.screenState==ScreenState::REWARDS && branch.info.rewardsContainer.cardRewardCount==1 && branch.info.rewardsContainer.goldRewardCount==1 && branch.info.rewardsContainer.relicCount==0,"bottle discarded remaining rewards");
        const int deck=branch.deck.size(),gold=branch.gold;
        search::GameAction(Type::CARD,0,0).execute(branch);search::GameAction(Type::GOLD,0).execute(branch);
        check(branch.deck.size()==deck+1 && branch.gold==gold+29,"remaining rewards could not be claimed");
        search::GameAction(Type::SKIP).execute(branch);check(branch.screenState==ScreenState::MAP_SCREEN,"reward continuation lost after bottle");
    }
    else if(mode=="campfire_toke") {
        g.relics.add({RelicId::PEACE_PIPE,0});g.screenState=ScreenState::REST_ROOM;g.regainControlAction=[](GameContext &a){a.screenState=ScreenState::MAP_SCREEN;};const int size=g.deck.size();
        search::GameAction(4).execute(g);check(g.screenState==ScreenState::CARD_SELECT && g.deck.size()==size,"Toke exited before card selection");
        search::GameAction(0).execute(g);check(g.deck.size()==size-1 && g.screenState==ScreenState::MAP_SCREEN,"Toke did not remove selected card and leave");
        g.deck=Deck();g.deck.obtainRaw(CardId::ASCENDERS_BANE);g.deck.obtainRaw(CardId::BASH);g.deck.bottleCard(1,CardType::ATTACK);g.screenState=ScreenState::REST_ROOM;
        check(!search::GameAction(4).isValidAction(g),"Toke allowed with no purgeable unbottled cards");

    }
    else if(mode=="stolen_reward_order") {
        g.curRoom=Room::MONSTER;g.info.stolenGold=40;g.afterBattle();
        check(g.info.rewardsContainer.goldRewardCount==2 && g.info.rewardsContainer.gold[0]==40,"stolen gold was not the first reward");
        const int gold=g.gold;search::GameAction(search::GameAction::RewardsActionType::GOLD,0).execute(g);
        check(g.gold==gold+40 && g.info.rewardsContainer.goldRewardCount==1,"claiming stolen gold consumed normal gold reward");
    }
    else if(mode=="victory_heal_order") {
        for(bool flower:{false,true})for(bool bloom:{false,true})for(int hp:{32,38}) {
            auto a=game();a.curHp=hp;a.maxHp=75;a.curRoom=Room::MONSTER;
            a.regainControlAction=[](GameContext &next){next.afterBattle();};
            a.relics.add({RelicId::MEAT_ON_THE_BONE,0});a.relics.add({RelicId::FACE_OF_CLERIC,0});
            if(flower)a.relics.add({RelicId::MAGIC_FLOWER,0});if(bloom)a.relics.add({RelicId::MARK_OF_THE_BLOOM,0});
            a.deck=Deck();for(int i=0;i<5;++i)a.deck.obtainRaw(Card(CardId::SEARING_BLOW,30));
            BattleContext b;b.init(a,MonsterEncounter::CULTIST);search::Action(search::ActionType::CARD,0,0).execute(b);
            check(b.outcome==Outcome::PLAYER_VICTORY,"healing fixture did not win");b.exitBattle(a);
            const int healing=(hp<=37?(flower?18:12):0)+(flower?9:6)+(flower?2:1);
            check(a.maxHp==76 && a.curHp==hp+(bloom?0:healing),"victory healing order or Magic Flower multiplier wrong");
        }
    }
    else if(mode=="mad_gremlin_rng") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);auto &m=b.monsters.arr[0];m.id=MonsterId::MAD_GREMLIN;m.setMove(MMID::MAD_GREMLIN_SCRATCH);
        const int counter=b.aiRng.counter;search::Action(search::ActionType::END_TURN).execute(b);
        check(b.aiRng.counter==counter,"Mad Gremlin fixed attack consumed AI RNG");
    }
    else if(mode=="original_event_ids") {
        for(auto pair:std::initializer_list<std::pair<Event,const char*>>{{Event::FACE_TRADER,"FaceTrader"},{Event::MATCH_AND_KEEP,"Match and Keep!"},{Event::MINDBLOOM,"MindBloom"},{Event::NLOTH,"N'loth"},{Event::NOTE_FOR_YOURSELF,"NoteForYourself"},{Event::SECRET_PORTAL,"SecretPortal"},{Event::SENSORY_STONE,"SensoryStone"}}) {
            check(std::string(eventIdStrings[static_cast<int>(pair.first)])==pair.second,"event protocol id differs from original");
            nlohmann::json encoded=pair.first;
            check(encoded.get<std::string>()==pair.second,"event save id differs from original");
            check(nlohmann::json(pair.second).get<Event>()==pair.first,"original event save id did not load");
        }
    }
    else if(mode=="heart_victory_floor") {
        g.act=4;g.floorNum=56;g.curRoom=Room::BOSS;g.info.encounter=MonsterEncounter::THE_HEART;g.afterBattle();
        check(g.outcome==GameOutcome::PLAYER_VICTORY && g.floorNum==57,"Heart victory did not enter final VictoryRoom");
    }
    else if(mode=="surrounded_death") {
        for(int target:{0,1}) {
            auto a=game();a.deck=Deck();for(int i=0;i<5;++i)a.deck.obtainRaw(Card(CardId::SEARING_BLOW,30));
            BattleContext b;b.init(a,MonsterEncounter::SHIELD_AND_SPEAR);
            check(b.player.hasStatus<PS::SURROUNDED>(),"Shield and Spear fixture missing Surrounded");
            search::Action(search::ActionType::CARD,0,target).execute(b);
            check(b.monsters.monstersAlive==1 && !b.player.hasStatus<PS::SURROUNDED>() && b.player.lastTargetedMonster==1-target,"killing one guardian left Surrounded or wrong facing");
        }
    }
    else if(mode=="bottle_curse" || mode=="bottle_all") {
        g.deck=Deck();for(auto id:{CardId::REGRET,CardId::STRIKE_RED,CardId::DEFEND_RED,CardId::INFLAME})g.deck.obtain(g,id);
        g.deck.bottleCard(1,CardType::ATTACK);
        if(mode=="bottle_all") {g.deck.bottleCard(2,CardType::SKILL);g.deck.bottleCard(3,CardType::POWER);check(g.deck.anyCardBottled(),"three bottles reported absent");}
        g.deck.remove(g,0);check(g.deck.bottleIdxs[0]==0,"curse removal shifted bottle to wrong card");consistent(g.deck);
    } else if(mode=="remove_selected") {
        g.deck=Deck();for(auto id:{CardId::ANGER,CardId::BASH,CardId::CLEAVE,CardId::DEFEND_RED})g.deck.obtain(g,id);
        fixed_list<SelectScreenCard,3> picked; picked.push_back({g.deck.cards[2],2});picked.push_back({g.deck.cards[0],0});
        g.deck.removeSelected(g,picked);check(g.deck.size()==2 && g.deck.cards[0].id==CardId::BASH && g.deck.cards[1].id==CardId::DEFEND_RED,"multi-removal removed wrong cards");consistent(g.deck);
    } else if(mode=="remove_all") {
        g.deck=Deck();g.deck.obtain(g,CardId::STRIKE_RED);g.deck.obtain(g,CardId::REGRET);int calls=0;
        g.deck.removeAllMatching(g,[&](const Card&c){++calls;return c.getType()==CardType::CURSE;});
        check(calls==2,"predicate inspected card outside deck");check(g.deck.size()==1,"curse not removed");consistent(g.deck);
    } else if(mode=="searing_upgrade") {
        g.deck=Deck();g.deck.obtain(g,CardId::SEARING_BLOW);g.deck.upgrade(0);g.deck.upgrade(0);
        check(g.deck.cards[0].getUpgraded()==2,"searing level lost");consistent(g.deck);
        check(Card(CardId::SEARING_BLOW,3).getUpgraded()==3,"constructor lost repeated upgrades");
    } else if(mode=="falling_bottled") {
        g.deck=Deck();for(auto id:{CardId::ASCENDERS_BANE,CardId::BASH,CardId::DEFEND_RED,CardId::INFLAME})g.deck.obtain(g,id);
        g.deck.bottleCard(1,CardType::ATTACK);g.curEvent=Event::FALLING;g.setupEvent();
        check(g.info.attackCardDeckIdx==-1,"Falling selected bottled attack");check(g.info.skillCardDeckIdx==2 && g.info.powerCardDeckIdx==3,"Falling lost unbottled candidates");
    } else if(mode=="golden_minimum") {
        g.maxHp=9;g.curHp=9;g.curEvent=Event::GOLDEN_IDOL;g.setupEvent();
        check(g.info.hpAmount1==1,"Golden Idol max HP cost rounded to zero");
    } else if(mode=="relic_rng_restore") {
        check(g.relicRng.counter==5,"relic pool shuffle draws missing from saved counter");
        Random restored(g.seed,g.relicRng.counter);
        check(restored.seed0==g.relicRng.seed0 && restored.seed1==g.relicRng.seed1,"relic RNG counter cannot restore next reward stream");
    } else if(mode=="rng_boundary") {
        for(int n:{0,250,500,750}) {auto a=game();a.cardRng.setCounter(n);a.transitionToAct(2);check(a.cardRng.counter==n,"act transition advanced exact RNG boundary");}
    } else if(mode=="missing_keys" || mode=="heart_route") {
        const MonsterEncounter bosses[]={MonsterEncounter::AWAKENED_ONE,MonsterEncounter::DONU_AND_DECA,MonsterEncounter::TIME_EATER};
        for(auto first:bosses)for(auto second:bosses)if(first!=second)for(int keys=0;keys<8;++keys){
            auto a=game();a.act=3;a.floorNum=50;a.curRoom=Room::BOSS;a.boss=first;a.secondBoss=second;a.info.encounter=first;
            a.redKey=keys&1;a.greenKey=keys&2;a.blueKey=keys&4;a.curHp=20;a.maxHp=80;
            a.afterBattle();check(a.info.encounter==second && a.outcome==GameOutcome::UNDECIDED,"A20 skipped second boss");check(a.curHp==20,"healed between Act 3 bosses");
            a.afterBattle();
            if(keys!=7) {if(mode=="missing_keys")check(a.outcome!=GameOutcome::PLAYER_VICTORY,"missing-key Act 3 ending counted as Heart victory");continue;}
            check(a.act==4 && a.outcome==GameOutcome::UNDECIDED && a.curHp==65,"Act 4 entry failed");
            const Room expected[]={Room::REST,Room::SHOP,Room::ELITE,Room::BOSS};
            for(int y=0;y<4;++y)check(a.map->getNode(3,y).room==expected[y],"Act 4 room order wrong");
            a.curRoom=Room::BOSS;a.info.encounter=MonsterEncounter::THE_HEART;a.afterBattle();check(a.outcome==GameOutcome::PLAYER_VICTORY,"Heart kill failed to end run");
        }
    } else if(mode=="gamble" || mode=="elixir" || mode=="potion_bounds") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();add(b,CardId::STRIKE_RED);add(b,CardId::DEFEND_RED);
        if(mode=="potion_bounds") {b.potions[b.potionCapacity]=Potion::FIRE_POTION;check(!search::Action(search::ActionType::POTION,b.potionCapacity,0).isValidAction(b),"out-of-capacity potion index accepted");return 0;}
        b.cards.drawPile.push_back(CardInstance(CardId::BASH));
        b.potions[0]=mode=="gamble"?Potion::GAMBLERS_BREW:Potion::ELIXIR_POTION;b.potionCount=1;
        search::Action(search::ActionType::POTION,0).execute(b);
        std::set<int> masks;for(auto a:sts::py::getLegalActions(b)) {check(a.isValidAction(b),"binding exposed illegal action");masks.insert(a.getSelectIdx());}
        check(masks==std::set<int>({0,1,2,3}),"binding omitted legal subsets");
        search::BattleScumSearcher2 searcher(b);searcher.enumerateActionsForNode(searcher.root,b);masks.clear();for(auto&e:searcher.root.edges)masks.insert(e.action.getSelectIdx());
        check(masks==std::set<int>({0,1,2,3}),"MCTS omitted legal subsets");
        search::Action(search::ActionType::MULTI_CARD_SELECT,1).execute(b);
        check(b.cards.cardsInHand==(mode=="gamble"?2:1),"selection/draw hand size wrong");
        if(mode=="gamble")check(b.cards.discardPile.size()==1 && b.cards.discardPile[0].id==CardId::STRIKE_RED,"selected card not discarded");
    } else if(mode=="sapphire_trade") {
        using Type=search::GameAction::RewardsActionType;
        for(int count:{1,2,3})for(int take=0;take<count;++take) {
            auto a=game();Rewards reward;const RelicId ids[]={RelicId::ANCHOR,RelicId::BAG_OF_MARBLES,RelicId::VAJRA};
            for(int i=0;i<count;++i)reward.addRelic(ids[i]);reward.sapphireKey=true;a.openCombatRewardScreen(reward);
            search::GameAction(Type::RELIC,take).execute(a);
            check(a.info.rewardsContainer.sapphireKey==(take!=count-1),"sapphire remained after its relic was taken, or disappeared for a bonus relic");
            if(take!=count-1) {search::GameAction(Type::KEY).execute(a);check(a.blueKey,"sapphire was not obtained");check(!a.hasRelic(ids[count-1]),"key and linked relic both obtained");}
        }
    } else if(mode=="potion_outside") {
        g.screenState=ScreenState::MAP_SCREEN;g.curMapNodeY=-1;g.potions[0]=Potion::BLOOD_POTION;g.potionCount=1;g.curHp=40;g.maxHp=80;
        const int floor=g.floorNum;search::GameAction drink(0x80000000U);check(drink.isValidAction(g),"blood potion illegal outside combat");drink.execute(g);
        check(g.curHp==56 && g.floorNum==floor && g.screenState==ScreenState::MAP_SCREEN,"outside potion also chose a room");
    } else if(mode=="potion_full_reward") {
        g.potions[0]=Potion::FIRE_POTION;g.potions[1]=Potion::BLOCK_POTION;g.potionCount=2;Rewards reward;reward.addPotion(Potion::BLOOD_POTION);g.openCombatRewardScreen(reward);
        search::GameAction take(search::GameAction::RewardsActionType::POTION,0);check(!take.isValidAction(g),"full-slot reward can be lost by claiming");
        search::GameAction(0xC0000000U).execute(g);check(take.isValidAction(g),"reward unavailable after making space");take.execute(g);check(g.potions[0]==Potion::BLOOD_POTION,"reward not placed in emptied slot");
    } else if(mode=="shop_a20") {
        auto lower=g;lower.ascension=15;Shop s0,s1;s0.setup(lower);s1.setup(g);
        for(int i=0;i<7;++i)check(s1.cardPrice(i)==std::round(s0.cardPrice(i)*1.1f),"A20 card price is not increased by 10 percent");
        for(int i=0;i<3;++i){check(s1.relicPrice(i)==std::round(s0.relicPrice(i)*1.1f),"A20 relic price wrong");check(s1.potionPrice(i)==std::round(s0.potionPrice(i)*1.1f),"A20 potion price wrong");}
    } else if(mode=="designer") {
        for(int option:{1,3,4}) {auto a=game();a.gold=200;a.curEvent=Event::DESIGNER_IN_SPIRE;a.curRoom=Room::EVENT;a.setupEvent();a.info.upgradeOne=false;a.info.cleanUpIsRemoveCard=false;
            a.regainControlAction=[](GameContext&x){x.screenState=ScreenState::MAP_SCREEN;};int hp=a.curHp;
            search::GameAction(option).execute(a);
            check(a.gold==200-(option==1?50:option==3?75:110),"designer charged wrong price");check(a.curHp==hp,"designer purchase also selected punch option");
            if(option==1)check(a.screenState==ScreenState::MAP_SCREEN,"random upgrade failed to finish");
            else {check(a.screenState==ScreenState::CARD_SELECT,"designer skipped card selection");const int n=option==3?2:1;for(int i=0;i<n;++i)search::GameAction(0).execute(a);check(a.screenState==ScreenState::MAP_SCREEN,"designer selection did not return");consistent(a.deck);}
        }
    } else if(mode=="colosseum") {
        g.curRoom=Room::EVENT;g.curEvent=Event::COLOSSEUM;g.setupEvent();g.skipBattles=true;const int floor=g.floorNum;
        search::GameAction(0).execute(g);check(g.info.eventData==1 && g.screenState==ScreenState::EVENT_SCREEN,"first Colosseum battle did not return to event");
        check(g.info.rewardsContainer.getTotalCount()==0,"first Colosseum fight granted rewards");
        search::GameAction(1).execute(g);check(g.floorNum==floor && g.screenState==ScreenState::REWARDS,"second Colosseum battle changed floor or skipped rewards");
        check(g.info.rewardsContainer.relicCount==2 && g.info.rewardsContainer.gold[0]==100 && g.info.rewardsContainer.cardRewardCount==1,"Colosseum second reward wrong");
    } else if(mode=="match_keep") {
        g.curRoom=Room::EVENT;g.curEvent=Event::MATCH_AND_KEEP;g.regainControlAction=[](GameContext&a){a.screenState=ScreenState::MAP_SCREEN;};g.setupEvent();
        const int deck=g.deck.size();
        for(int pair=0;pair<5;++pair) {
            int first=-1,second=-1;for(int i=0;i<12 && first<0;++i)for(int j=i+1;j<12;++j)if(g.info.toSelectCards[i].card.id!=CardId::INVALID && g.info.toSelectCards[i].card.id==g.info.toSelectCards[j].card.id){first=i;second=j;break;}
            check(first>=0,"match pair unavailable");search::GameAction(first).execute(g);check(!search::GameAction(first).isValidAction(g),"same tile can be selected twice");search::GameAction(second).execute(g);
            if(pair<4)check(!search::GameAction(first).isValidAction(g),"matched tile can be collected twice");
        }
        check(g.screenState==ScreenState::MAP_SCREEN && g.deck.size()==deck+5,"match game did not finish after five attempts");consistent(g.deck);
    } else if(mode=="darkstone") {
        g.relics.add({RelicId::DARKSTONE_PERIAPT,0});const int hp=g.maxHp;g.deck.obtain(g,CardId::REGRET);check(g.maxHp==hp+6,"curse did not trigger Darkstone");
        g.relics.add({RelicId::OMAMORI,1});g.deck.obtain(g,CardId::REGRET);check(g.maxHp==hp+6,"blocked curse triggered Darkstone");consistent(g.deck);
    } else if(mode=="smoke_escape") {
        g.curRoom=Room::MONSTER;g.regainControlAction=[](GameContext&a){a.afterBattle();};g.curHp=30;g.maxHp=80;
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.player.curHp=30;b.potions[0]=Potion::SMOKE_BOMB;b.potionCount=1;
        const auto treasure=g.treasureRng.counter,card=g.cardRng.counter,potion=b.potionRng.counter;
        search::Action use(search::ActionType::POTION,0);check(use.isValidAction(b),"normal Smoke Bomb rejected");use.execute(b);
        check(b.isBattleOver && b.outcome!=Outcome::PLAYER_VICTORY && b.outcome!=Outcome::UNDECIDED,"escape treated as kill or did not end combat");
        b.exitBattle(g);check(g.curHp==36,"Smoke Bomb omitted Burning Blood recovery");
        check(g.screenState==ScreenState::REWARDS && g.info.rewardsContainer.getTotalCount()==0,"escape gave rewards");
        check(g.treasureRng.counter==treasure+1 && g.potionRng.counter>potion && g.cardRng.counter==card,"escape changed subsequent RNG incorrectly");
    } else if(mode=="smoke_illegal") {
        for(auto encounter:{MonsterEncounter::SLIME_BOSS,MonsterEncounter::THE_HEART,MonsterEncounter::SHIELD_AND_SPEAR}) {
            BattleContext b;b.init(g,encounter);b.potions[0]=Potion::SMOKE_BOMB;b.potionCount=1;
            check(!search::Action(search::ActionType::POTION,0).isValidAction(b),"smoke allowed against boss or Back Attack");
            for(const auto&a:sts::py::getLegalActions(b))check(a.isValidAction(b),"binding advertised illegal potion");
            search::BattleScumSearcher2 s(b);s.enumerateActionsForNode(s.root,b);for(const auto&e:s.root.edges)check(e.action.isValidAction(b),"MCTS advertised illegal potion");
        }
    } else if(mode=="fairy_outside") {
        g.maxHp=80;g.curHp=1;g.potions[0]=Potion::FAIRY_POTION;g.potionCount=1;g.relics.add({RelicId::SACRED_BARK,0});g.playerLoseHp(2);
        check(g.curHp==48 && g.potionCount==0 && g.outcome==GameOutcome::UNDECIDED,"Sacred Bark Fairy restored wrong HP outside battle");
    } else if(mode=="forethought") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();add(b,CardId::STRIKE_RED);add(b,CardId::BASH);add(b,CardId::DEFEND_RED);
        b.addToBot(Actions::ForethoughtAction(true));b.inputState=InputState::EXECUTING_ACTIONS;b.executeActions();
        check(search::Action(search::ActionType::MULTI_CARD_SELECT,0).isValidAction(b),"Forethought+ cannot select zero");
        search::Action(search::ActionType::SINGLE_CARD_SELECT,2).execute(b);auto alternate=b;
        check(!search::Action(search::ActionType::SINGLE_CARD_SELECT,2).isValidAction(b),"Forethought can select one card twice");
        search::Action(search::ActionType::SINGLE_CARD_SELECT,0).execute(b);search::Action(search::ActionType::MULTI_CARD_SELECT,0).execute(b);
        check(b.cards.cardsInHand==1 && b.cards.hand[0].id==CardId::BASH,"Forethought+ moved wrong subset");
        check(b.cards.drawPile[0].id==CardId::STRIKE_RED && b.cards.drawPile[1].id==CardId::DEFEND_RED && b.cards.drawPile[0].freeToPlayOnce,"Forethought+ lost order or free play");
        search::Action(search::ActionType::MULTI_CARD_SELECT,0).execute(alternate);check(alternate.cards.cardsInHand==2,"selection branch contaminated sibling");
    } else if(mode=="toy_ornithopter") {
        auto outside=game();outside.curHp=40;outside.maxHp=80;outside.relics.add({RelicId::TOY_ORNITHOPTER,0});
        outside.potions[0]=Potion::BLOOD_POTION;outside.potionCount=1;outside.drinkPotionAtIdx(0);
        check(outside.curHp==61,"Toy Ornithopter did not heal after an outside potion");
        auto combat=game();combat.curHp=40;combat.maxHp=80;combat.curRoom=Room::MONSTER;combat.info.encounter=MonsterEncounter::CULTIST;
        combat.relics.add({RelicId::TOY_ORNITHOPTER,0});BattleContext b;b.init(combat);b.potions[0]=Potion::BLOOD_POTION;b.potionCount=1;
        search::Action(search::ActionType::POTION,0).execute(b);
        check(b.player.curHp==61,"Toy Ornithopter did not heal after an in-combat potion");
    } else if(mode=="console_forethought") {
        auto start=game();start.curRoom=Room::MONSTER;start.info.encounter=MonsterEncounter::CULTIST;
        BattleSimulator sim;sim.initBattle(start);sim.bc->cards=CardManager();
        add(*sim.bc,CardId::STRIKE_RED);add(*sim.bc,CardId::BASH);add(*sim.bc,CardId::DEFEND_RED);
        sim.bc->addToBot(Actions::ForethoughtAction(true));sim.bc->inputState=InputState::EXECUTING_ACTIONS;sim.bc->executeActions();
        std::ostringstream prompt;sim.printCardSelectActions(prompt);
        check(prompt.str().find("Forethought+")!=std::string::npos,"console did not describe upgraded Forethought selection");
        SimulatorContext context;sim.handleInputLine("2 0",prompt,context);
        check(sim.bc->cards.cardsInHand==1 && sim.bc->cards.hand[0].id==CardId::BASH,"console Forethought moved wrong subset");
        check(sim.bc->cards.drawPile.size()>=2 && sim.bc->cards.drawPile[0].id==CardId::STRIKE_RED && sim.bc->cards.drawPile[1].id==CardId::DEFEND_RED,"console Forethought lost selection order");
    } else if(mode=="liquid_memories") {
        for(int full:{0,9,10}) {
            BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();for(int i=0;i<full;++i)add(b,CardId::DEFEND_RED);
            for(auto id:{CardId::STRIKE_RED,CardId::BASH,CardId::CLEAVE}){CardInstance c(id);c.uniqueId=b.cards.nextUniqueCardId++;b.cards.notifyAddCardToCombat(c);b.cards.moveToDiscardPile(c);}
            b.addToBot(Actions::BetterDiscardPileToHandAction(2,CardSelectTask::LIQUID_MEMORIES_POTION));b.inputState=InputState::EXECUTING_ACTIONS;b.executeActions();
            search::Action(search::ActionType::SINGLE_CARD_SELECT,2).execute(b);check(b.inputState==InputState::CARD_SELECT,"two-card potion ended after first choice");
            check(!search::Action(search::ActionType::SINGLE_CARD_SELECT,2).isValidAction(b),"potion can select same card twice");
            search::Action(search::ActionType::SINGLE_CARD_SELECT,0).execute(b);
            check(b.cards.cardsInHand==std::min(10,full+2),"potion retrieved wrong count");
            if(full<10)check(b.cards.hand[full].id==CardId::CLEAVE && b.cards.hand[full].costForTurn==0,"potion lost selected order or zero cost");
            if(full==10)check(b.cards.discardPile.size()==3 && b.cards.discardPile[2].costForTurn==1,"full hand changed unreceived card");
        }
    } else if(mode=="rewards_count") {
        Rewards r(RelicId::ANCHOR);check(r.getTotalCount()==1,"relic-only reward counted empty");r.addCardReward(CardReward{CardId::BASH});r.addCardReward(CardReward{CardId::CLEAVE});r.removeCardReward(0);check(r.cardRewardCount==1 && r.cardRewards[0][0].id==CardId::CLEAVE,"card reward removal changed survivor");
    } else if(mode=="map_isolation") {
        auto a=g;const auto old=g.map;a.transitionToAct(4);check(g.map==old && a.map!=g.map,"branch transition overwrote shared map");check(g.map->getNode(3,0).room!=Room::REST || g.map->getNode(3,1).room!=Room::SHOP,"parent map became Act 4");
    } else if(mode=="sozu_outside") {
        g.relics.add({RelicId::SOZU,0});const auto counter=g.potionRng.counter;const int count=g.potionCount;g.drinkPotion(Potion::ENTROPIC_BREW);check(g.potionCount==count && g.potionRng.counter==counter,"outside Entropic Brew bypassed Sozu");
    } else if(mode=="awakened_pending_rebirth") {
        BattleContext b;b.init(g,MonsterEncounter::AWAKENED_ONE);
        b.monsters.arr[2].damage(b,999);check(b.monsters.arr[2].halfDead,"Awakened One did not enter rebirth");
        b.monsters.arr[0].damage(b,999);b.monsters.arr[1].damage(b,999);
        check(b.outcome==Outcome::UNDECIDED && !b.monsters.areMonstersBasicallyDead(),"last Cultist kill ended fight before rebirth");
        search::Action(search::ActionType::END_TURN).execute(b);
        check(b.monsters.arr[2].curHp==320 && !b.monsters.arr[2].halfDead,"Awakened One failed to revive");
        b.monsters.arr[2].damage(b,999);check(b.outcome==Outcome::PLAYER_VICTORY,"second Awakened death failed to end fight");
    } else if(mode=="untargetable_card_bounds") {
        BattleContext b;b.init(g,MonsterEncounter::AWAKENED_ONE);
        CardInstance attack(CardId::STRIKE_RED),defend(CardId::DEFEND_RED);
        b.player.energy=3;
        check(attack.canUse(b,2,false),"live Awakened One should be targetable");
        b.monsters.arr[2].damage(b,999);
        b.monsters.arr[0].damage(b,999);b.monsters.arr[1].damage(b,999);
        check(b.monsters.getFirstTargetable()==-1 && !b.monsters.areMonstersBasicallyDead(),"fixture must wait for rebirth without a target");
        check(!attack.canUseOnAnyTarget(b),"targeted card playable without a live target");
        for(int target:{-1,3,5,999})check(!attack.canUse(b,target,false),"invalid monster index accepted");
        check(defend.canUseOnAnyTarget(b),"rebirth gap must still allow non-targeted cards");
        search::Action(search::ActionType::END_TURN).execute(b);
        b.player.energy=3;
        check(attack.canUseOnAnyTarget(b) && attack.canUse(b,2,false),"attack remained blocked after rebirth");
    } else if(mode=="havoc_unplayable") {
        for(auto id:{CardId::WOUND,CardId::ASCENDERS_BANE,CardId::BURN}) {
            BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();add(b,CardId::HAVOC);addDrawTop(b,id);
            const int hp=b.player.curHp;search::Action(search::ActionType::CARD,0,0).execute(b);
            check(b.cards.drawPile.empty(),"Havoc left the top card in the draw pile");
            check(b.cards.exhaustPile.size()==1 && b.cards.exhaustPile[0].id==id,"Havoc lost an unplayable top card instead of exhausting it");
            check(b.player.curHp==hp,"Havoc triggered the effect of an unplayable status card");
            check(b.player.cardsPlayedThisTurn==1,"unplayable Havoc target counted as a played card");

            BattleContext noExhaust;noExhaust.init(g,MonsterEncounter::CULTIST);noExhaust.cards=CardManager();addDrawTop(noExhaust,id);
            const int noExhaustHp=noExhaust.player.curHp;noExhaust.addToBot(Actions::PlayTopCard(0,false));noExhaust.inputState=InputState::EXECUTING_ACTIONS;noExhaust.executeActions();
            check(noExhaust.cards.drawPile.empty() && noExhaust.cards.exhaustPile.empty(),"non-exhausting autoplay left an unplayable card in the wrong pile");
            check(noExhaust.cards.discardPile.size()==1 && noExhaust.cards.discardPile[0].id==id,"Mayhem or Distilled Chaos lost an unplayable top card instead of discarding it");
            check(noExhaust.player.curHp==noExhaustHp && noExhaust.player.cardsPlayedThisTurn==0,"non-exhausting autoplay triggered an unplayable card");
        }
    } else if(mode=="true_grit_rng") {
        {
            BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();add(b,CardId::TRUE_GRIT);add(b,CardId::DEFEND_RED);
            const auto before=b.cardRandomRng;search::Action(search::ActionType::CARD,0,0).execute(b);
            check(b.cardRandomRng.counter==before.counter && b.cardRandomRng.seed0==before.seed0 && b.cardRandomRng.seed1==before.seed1,"True Grit consumed RNG with one exhaust candidate");
            check(b.cards.exhaustPile.size()==1 && b.cards.exhaustPile[0].id==CardId::DEFEND_RED,"True Grit did not exhaust its sole candidate");
        }
        {
            BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();add(b,CardId::TRUE_GRIT);add(b,CardId::DEFEND_RED);add(b,CardId::STRIKE_RED);
            const int before=b.cardRandomRng.counter;search::Action(search::ActionType::CARD,0,0).execute(b);
            check(b.cardRandomRng.counter==before+1,"True Grit skipped RNG with multiple exhaust candidates");
        }
        {
            BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();add(b,CardId::FIEND_FIRE);add(b,CardId::DEFEND_RED);
            const int before=b.cardRandomRng.counter;search::Action(search::ActionType::CARD,0,0).execute(b);
            check(b.cardRandomRng.counter==before+1,"Fiend Fire lost its one-card random draw");
        }
    } else if(mode=="violence_sparse") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();add(b,CardId::VIOLENCE);
        addDrawTop(b,CardId::DEFEND_RED);addDrawTop(b,CardId::STRIKE_RED);addDrawTop(b,CardId::WOUND);
        search::Action(search::ActionType::CARD,0,0).execute(b);
        check(b.cards.cardsInHand==1 && b.cards.hand[0].id==CardId::STRIKE_RED,"Violence did not move the only attack to hand");
        check(b.cards.drawPile.size()==2,"Violence duplicated an attack when fewer cards were available than requested");
        for(const auto &c:b.cards.drawPile)check(c.id!=CardId::STRIKE_RED,"Violence left the selected attack in the draw pile");
    } else if(mode=="generated_blood_cost") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.player.timesDamagedThisCombat=3;
        b.chooseCodexCard(CardId::BLOOD_FOR_BLOOD);
        bool found=false;for(auto c:b.cards.drawPile)if(c.id==CardId::BLOOD_FOR_BLOOD){check(c.cost==1 && c.costForTurn==1,"Codex Blood for Blood forgot earlier damage");found=true;}
        check(found,"Codex did not add generated card");
        check(b.createGeneratedCard(CardId::BLOOD_FOR_BLOOD,true).cost==0,"upgraded generated Blood for Blood cost wrong");
        check(b.createGeneratedCard(CardId::BASH).cost==2,"unrelated generated card cost changed");
    } else if(mode=="buffer_hp_loss") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.player.curHp=50;b.player.buff<PS::BUFFER>(1);
        b.player.loseHp(b,6,true);check(b.player.curHp==50 && !b.player.hasStatus<PS::BUFFER>(),"Offering bypassed Buffer");
        b.player.loseHp(b,6,true);check(b.player.curHp==44,"Buffer prevented a second HP loss");
        b.player.setHasRelic<RelicId::MAGIC_FLOWER>(true);b.player.heal(3);check(b.player.curHp==49,"Magic Flower failed original rounding");
    } else if(mode=="mummified_candidates") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();
        for(auto id:{CardId::INFLAME,CardId::DEFEND_RED,CardId::STRIKE_RED,CardId::STRIKE_RED,CardId::STRIKE_RED,CardId::BASH,CardId::OFFERING,CardId::STRIKE_RED,CardId::STRIKE_RED,CardId::DEFEND_RED})add(b,id);
        b.player.setHasRelic<RelicId::MUMMIFIED_HAND>(true);b.cardRandomRng=Random(123);
        search::Action(search::ActionType::CARD,0,0).execute(b);
        check(b.cards.hand[6].costForTurn==0 && b.cards.hand[0].costForTurn==1,"Mummified Hand included power being played");
        CardQueue queue;CardInstance a(CardId::BASH),c(CardId::DEFEND_RED);a.uniqueId=41;c.uniqueId=42;
        queue.pushBack(CardQueueItem(a,0,0));queue.pushBack(CardQueueItem(c,0,0));
        check(queue.containsCardWithId(42),"queued candidate beyond front was invisible");
        queue.popFront();check(!queue.containsCardWithId(41) && queue.containsCardWithId(42),"popped card remained queued");
    } else if(mode=="stat_caps") {
        Player p;p.strength=600;p.buff<PS::STRENGTH>(600);check(p.strength==999,"Limit Break exceeded Strength cap");
        p.dexterity=-998;p.debuff<PS::DEXTERITY>(-5);check(p.dexterity==-999,"Dexterity exceeded negative cap");
        Monster m;m.strength=-998;m.addDebuff<MS::STRENGTH>(-15,false);check(m.strength==-999,"Shackles exceeded negative Strength cap");
        m.buff<MS::STRENGTH>(15);check(m.strength==-984,"temporary Strength recovery ignored clamping loss");
    } else if(mode=="portal_time") {
        g.act=3;check(!g.canAddOneTimeEvent(Event::SECRET_PORTAL),"fresh run admits timed portal");
        g.speedrunPace=false;check(g.canAddOneTimeEvent(Event::SECRET_PORTAL),"elapsed-time threshold did not admit portal");
        g.act=2;check(!g.canAddOneTimeEvent(Event::SECRET_PORTAL),"portal admitted outside Act 3");
    } else if(mode=="monster_hp_ranges") {
        for(int seed=0;seed<64;++seed) {
            for(auto id:{MonsterId::AWAKENED_ONE,MonsterId::CENTURION}) {
                Random rng(seed),expected(seed);Monster m;m.id=id;m.initHp(rng,20);
                const int hp=id==MonsterId::AWAKENED_ONE?expected.random(320,320):expected.random(78,83);
                check(m.maxHp==hp && rng.counter==expected.counter,"original A20 HP range differs");
            }
        }
    } else if(mode=="mugger_death_rng") {
        for(bool last:{false,true}) {
            BattleContext b;b.init(g,MonsterEncounter::TWO_THIEVES);
            if(last){b.monsters.arr[0].curHp=0;b.monsters.monstersAlive=1;}
            auto expected=b.aiRng;expected.random(2);b.monsters.arr[1].damage(b,999);
            check(b.aiRng.counter==expected.counter && b.aiRng.seed0==expected.seed0 && b.aiRng.seed1==expected.seed1,"Mugger death omitted sound RNG");
        }
        BattleContext b;b.init(g,MonsterEncounter::LOOTER);const auto counter=b.aiRng.counter;b.monsters.arr[0].damage(b,999);
        check(b.aiRng.counter==counter,"Looter death consumed gameplay RNG");
    } else if(mode=="monster_stacks") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);auto&m=b.monsters.arr[0];m.addDebuff<MonsterStatus::POISON>(150, false);check(m.getStatus<MonsterStatus::POISON>()==150,"poison stack overflow");m.buff<MonsterStatus::SHACKLED>(150);check(m.getStatus<MonsterStatus::SHACKLED>()==150,"temporary strength stack overflow");
    } else if(mode=="ritual_permanent") {
        g.deck=Deck();g.deck.obtainRaw(CardId::RITUAL_DAGGER);g.curRoom=Room::MONSTER;g.regainControlAction=[](GameContext&a){a.afterBattle();};
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.monsters.arr[0].curHp=10;
        check(b.cards.hand[0].specialData==15,"fresh Ritual Dagger did not start at 15 damage");
        search::Action(search::ActionType::CARD,0,0).execute(b);check(b.outcome==Outcome::PLAYER_VICTORY,"Ritual Dagger did not kill target");b.exitBattle(g);check(g.deck.cards[0].misc==18,"killing-blow Ritual Dagger increase did not survive battle exit");
        BattleContext next;next.init(g,MonsterEncounter::CULTIST);check(next.cards.hand[0].specialData==18,"next battle lost Ritual Dagger increase");
    } else if(mode=="training_observation") {
        const auto *nn=NNInterface::getInstance();
        const auto maximums=nn->getObservationMaximums();
        check(maximums[3]==60,"floor normalization maximum was overwritten");
        check(static_cast<int>(maximums.size())==NNInterface::observation_space_size,"observation maximum size differs from observation contract");

        auto base=game();base.deck=Deck();
        const auto empty=nn->getObservation(base);

        auto keys=base;keys.greenKey=true;keys.redKey=true;keys.blueKey=true;
        check(nn->getObservation(keys)!=empty,"keys are absent from training observation");
        check(nn->getObservation(keys)[NNInterface::keyOffset]==1 && nn->getObservation(keys)[NNInterface::keyOffset+1]==1 && nn->getObservation(keys)[NNInterface::keyOffset+2]==1,"key observation order is wrong");

        auto potion=base;potion.potions[0]=Potion::FIRE_POTION;potion.potionCount=1;
        check(nn->getObservation(potion)!=empty,"potion inventory is absent from training observation");

        auto anger=base;anger.deck.obtainRaw(CardId::ANGER);
        auto curse=base;curse.deck.obtainRaw(CardId::ASCENDERS_BANE);
        auto regret=base;regret.deck.obtainRaw(CardId::REGRET);
        check(nn->getObservation(anger)!=nn->getObservation(curse) && nn->getObservation(anger)!=nn->getObservation(regret),"distinct card ids collide in training observation");

        auto searing1=base;searing1.deck.obtainRaw(Card(CardId::SEARING_BLOW,1));
        auto searing5=base;searing5.deck.obtainRaw(Card(CardId::SEARING_BLOW,5));
        check(nn->getObservation(searing1)!=nn->getObservation(searing5),"Searing Blow upgrade count is absent from training observation");

        Card ritual15(CardId::RITUAL_DAGGER),ritual99(CardId::RITUAL_DAGGER);ritual99.misc=99;
        auto dagger15=base;dagger15.deck.obtainRaw(ritual15);
        auto dagger99=base;dagger99.deck.obtainRaw(ritual99);
        check(nn->getObservation(dagger15)!=nn->getObservation(dagger99),"card misc value is absent from training observation");

        Card ritual30(CardId::RITUAL_DAGGER),ritual84(CardId::RITUAL_DAGGER);ritual30.misc=30;ritual84.misc=84;
        auto sameSumA=base;sameSumA.deck.obtainRaw(ritual15);sameSumA.deck.obtainRaw(ritual99);
        auto sameSumB=base;sameSumB.deck.obtainRaw(ritual30);sameSumB.deck.obtainRaw(ritual84);
        check(nn->getObservation(sameSumA)!=nn->getObservation(sameSumB),"different Ritual Dagger values collapse to the same aggregate");

        auto hiddenA=base;hiddenA.curEvent=Event::MATCH_AND_KEEP;hiddenA.screenState=ScreenState::EVENT_SCREEN;
        hiddenA.info.toSelectCards={{Card(CardId::ANGER),-1},{Card(CardId::BASH),-1}};
        auto hiddenB=hiddenA;hiddenB.info.toSelectCards[0].card=Card(CardId::RITUAL_DAGGER);
        check(nn->getObservation(hiddenA)==nn->getObservation(hiddenB),"training observation leaks unrevealed Match and Keep cards");
        hiddenA.info.matchFirst=0;hiddenA.info.toSelectCards[0].deckIdx=1;
        hiddenB.info.matchFirst=0;hiddenB.info.toSelectCards[0].deckIdx=1;
        check(nn->getObservation(hiddenA)!=nn->getObservation(hiddenB),"revealed Match and Keep card is absent from training observation");

        auto selectedA=base;selectedA.info.haveSelectedCards.push_back({Card(CardId::ANGER),3});
        auto selectedB=base;selectedB.info.haveSelectedCards.push_back({Card(CardId::BASH),3});
        check(nn->getObservation(selectedA)!=nn->getObservation(selectedB),"multi-card selection history is absent from training observation");

        auto eventState=base;eventState.info.hpAmount0=7;eventState.info.goldLoss=42;
        check(nn->getObservation(eventState)!=empty,"visible event amounts are absent from training observation");
        auto eventEncounter=base;eventEncounter.info.encounter=MonsterEncounter::LAGAVULIN_EVENT;
        check(nn->getObservation(eventEncounter)!=empty,"visible event encounter is absent from training observation");

        auto relic0=base;relic0.obtainRelic(RelicId::PEN_NIB);relic0.relics.getRelicValueRef(RelicId::PEN_NIB)=0;
        auto relic9=relic0;relic9.relics.getRelicValueRef(RelicId::PEN_NIB)=9;
        check(nn->getObservation(relic0)!=nn->getObservation(relic9),"relic counter is absent from training observation");

        auto highRelic=base;highRelic.obtainRelic(RelicId::RED_CIRCLET);
        const auto highObservation=nn->getObservation(highRelic);
        check(highObservation[NNInterface::relicPresenceOffset+static_cast<int>(RelicId::RED_CIRCLET)]==1,"late relic ids overflow or disappear from training observation");

        auto bottled=anger;bottled.deck.bottleCard(0,CardType::ATTACK);
        check(nn->getObservation(bottled)!=nn->getObservation(anger),"bottled-card state is absent from training observation");
    } else if(mode=="training_all_decisions") {
        search::ScumSearchAgent2 agent;agent.pauseOnAllOutOfCombatDecisions=true;
        const auto expectPause=[&](GameContext &state,const char *message){agent.playout(state);check(agent.paused,message);check(!search::GameAction::getAllActionsInState(state).empty(),"paused screen has no legal actions");};

        auto excluded=game();
        check(std::find(excluded.shopRelicPool.begin(),excluded.shopRelicPool.end(),RelicId::PRISMATIC_SHARD)==excluded.shopRelicPool.end(),"disabled Prismatic Shard remains in the shop relic pool");

        auto event=game();expectPause(event,"external policy did not receive event choice");
        auto map=game();map.screenState=ScreenState::MAP_SCREEN;expectPause(map,"external policy did not receive map choice");
        auto rest=game();rest.curRoom=Room::REST;rest.screenState=ScreenState::REST_ROOM;expectPause(rest,"external policy did not receive campfire choice");
        auto treasure=game();treasure.screenState=ScreenState::TREASURE_ROOM;treasure.info.chestSize=ChestSize::MEDIUM;expectPause(treasure,"external policy did not receive treasure choice");
        auto boss=game();boss.screenState=ScreenState::BOSS_RELIC_REWARDS;boss.info.bossRelics[0]=RelicId::BLACK_BLOOD;boss.info.bossRelics[1]=RelicId::BLACK_STAR;boss.info.bossRelics[2]=RelicId::CALLING_BELL;expectPause(boss,"external policy did not receive boss relic choice");

        auto upgrade=game();upgrade.curRoom=Room::REST;upgrade.screenState=ScreenState::REST_ROOM;search::GameAction(1).execute(upgrade);check(upgrade.screenState==ScreenState::CARD_SELECT,"campfire upgrade did not open card selection");expectPause(upgrade,"external policy did not receive upgrade target choice");

        auto remove=game();remove.curRoom=Room::SHOP;remove.screenState=ScreenState::SHOP_ROOM;for(auto &price:remove.info.shop.prices)price=-1;remove.info.shop.removeCost=75;search::GameAction(search::GameAction::RewardsActionType::CARD_REMOVE).execute(remove);check(remove.screenState==ScreenState::CARD_SELECT,"shop removal did not open card selection");expectPause(remove,"external policy did not receive removal target choice");

        auto green=game();Rewards emerald;emerald.emeraldKey=true;green.openCombatRewardScreen(emerald);expectPause(green,"external policy did not receive emerald key choice");check(offered(green,search::GameAction(search::GameAction::RewardsActionType::KEY)),"emerald key missing from legal actions");search::GameAction(search::GameAction::RewardsActionType::KEY).execute(green);check(green.greenKey,"external key action did not obtain emerald key");

        Rewards sapphire;sapphire.addRelic(RelicId::ANCHOR);sapphire.sapphireKey=true;green.openCombatRewardScreen(sapphire);expectPause(green,"external policy did not receive sapphire key choice");search::GameAction(search::GameAction::RewardsActionType::KEY).execute(green);check(green.blueKey && green.info.rewardsContainer.relicCount==0,"sapphire key did not trade away linked chest relic");

        green.curRoom=Room::REST;green.screenState=ScreenState::REST_ROOM;green.regainControlAction=[](GameContext &next){next.screenState=ScreenState::MAP_SCREEN;};search::GameAction(2).execute(green);check(green.redKey,"Recall did not obtain ruby key");
        green.act=3;green.floorNum=50;green.curRoom=Room::BOSS;green.boss=MonsterEncounter::AWAKENED_ONE;green.secondBoss=MonsterEncounter::TIME_EATER;green.info.encounter=green.boss;green.afterBattle();green.afterBattle();
        check(green.act==4 && green.outcome==GameOutcome::UNDECIDED,"three externally selected keys did not enter Act 4");
    } else if(mode=="temporary_cost") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.cards=CardManager();add(b,CardId::BLUDGEON);b.cards.hand[0].costForTurn=0;
        search::Action(search::ActionType::CARD,0,0).execute(b);check(b.cards.discardPile.back().costForTurn==3,"played temporary-free card remained free in discard");
        CardInstance permanent(CardId::BLUDGEON);permanent.cost=0;permanent.costForTurn=0;b.cards.moveToDiscardPile(permanent);check(b.cards.discardPile.back().costForTurn==0,"permanent cost change was lost");
    } else if(mode=="darkling_chomp") {
        BattleContext b;b.init(g,MonsterEncounter::THREE_DARKLINGS);b.player.curHp=80;b.player.block=0;
        for(int i=1;i<3;++i)b.monsters.arr[i].curHp=0;b.monsters.monstersAlive=1;b.monsters.arr[0].setMove(MMID::DARKLING_CHOMP);
        search::Action(search::ActionType::END_TURN).execute(b);check(b.player.curHp==62,"Darkling Chomp did not hit twice at A20");
    } else if(mode=="red_entangle") {
        BattleContext b;b.init(g,MonsterEncounter::RED_SLAVER);b.monsters.arr[0].setMove(MMID::RED_SLAVER_ENTANGLE);search::Action(search::ActionType::END_TURN).execute(b);check(b.monsters.arr[0].miscInfo==1,"Red Slaver forgot using Entangle");
    } else if(mode=="hexaghost_burns") {
        BattleContext b;b.init(g,MonsterEncounter::HEXAGHOST);b.player.curHp=80;b.monsters.arr[0].setMove(MMID::HEXAGHOST_INFERNO);b.cards=CardManager();b.cards.drawPile.push_back(CardInstance(CardId::BURN));
        search::Action(search::ActionType::END_TURN).execute(b);int burns=0;for(int i=0;i<b.cards.cardsInHand;++i){auto&c=b.cards.hand[i];if(c.id==CardId::BURN){++burns;check(c.upgraded,"Inferno left burn unupgraded");}}for(auto&c:b.cards.discardPile)if(c.id==CardId::BURN){++burns;check(c.upgraded,"new burn unupgraded");}
        check(burns==4,"Inferno omitted its three new burns");
    } else if(mode=="bomb_stacks") {
        BattleContext b;b.init(g,MonsterEncounter::CULTIST);b.player.curHp=200;b.player.maxHp=200;b.monsters.arr[0].curHp=200;b.monsters.arr[0].maxHp=200;
        for(int i=0;i<4;++i)b.player.buff<PS::THE_BOMB>(40);
        for(int i=0;i<3;++i)search::Action(search::ActionType::END_TURN).execute(b);
        check(b.monsters.arr[0].curHp==40,"four bombs overflowed their damage counter");
    } else throw std::runtime_error("unknown test");
    std::cout<<"PASS "<<mode<<'\n';
}catch(const std::exception&e){std::cerr<<"FAIL "<<argv[1]<<": "<<e.what()<<'\n';return 1;}}
