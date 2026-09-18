#include "game/GameContext.h"
#include "combat/BattleContext.h"
#include "sim/search/GameAction.h"
#include "sim/search/ScumSearchAgent2.h"
#include <nlohmann/json.hpp>
#include <iostream>
#include <sstream>
#include <fstream>
using namespace sts;using namespace sts::search;using json=nlohmann::json;
bool reaches(const GameContext&g,int x,int y){
 if(y==g.map->burningEliteY)return x==g.map->burningEliteX;
 if(y>g.map->burningEliteY || y>=14)return false;
 const auto&n=g.map->getNode(x,y);for(int i=0;i<n.edgeCount;++i)if(reaches(g,n.edges[i],y+1))return true;return false;
}
double routeScore(const GameContext&g,int x,int y){
 if(y>=15)return 0;
 const auto&node=g.map->getNode(x,y);double best=-1000000;
 for(int i=0;i<node.edgeCount;i++)best=std::max(best,routeScore(g,node.edges[i],y+1));
 if(node.edgeCount==0)best=0;
 double value=node.room==Room::ELITE?-5:(node.room==Room::REST?4:(node.room==Room::SHOP?(g.gold>=150?2:0):1));
 return value+best;
}
int main(int argc,char**argv){
 const bool safeRest=argc>2&&std::string(argv[2])=="natural-rest";const bool validation=argc>2&&std::string(argv[2])=="validation";const auto seed=std::stoull(argv[1]);const bool controlled=argc>2 && std::string(argv[2])=="controlled";GameContext g(CharacterClass::IRONCLAD,seed,20);ScumSearchAgent2 agent;agent.simulationCountBase=argc>3?std::stoi(argv[3]):1000;
 std::ofstream progress;if(argc>4)progress.open(argv[4]);
 agent.printActions=true;std::ostringstream actionLog;auto*outputBuffer=std::cout.rdbuf(actionLog.rdbuf());
 json result={{"seed",seed},{"controlled_fixture",controlled},{"validation_policy",validation},{"final_act_rest_policy",safeRest},{"budget",agent.simulationCountBase},{"steps",json::array()}};
 if(controlled){g.curHp=g.maxHp=2000;g.deck=Deck();for(int i=0;i<5;++i)g.deck.obtainRaw(Card(CardId::SEARING_BLOW,30));for(auto r:{RelicId::COFFEE_DRIPPER,RelicId::FUSION_HAMMER,RelicId::CURSED_KEY,RelicId::SOZU})g.relics.add({r,0});result["fixture"]="2000 HP, five Searing Blow+30, Coffee Dripper/Fusion Hammer/Cursed Key/Sozu";}
 try{
  // Reuse an actual recorded prefix by replaying actions, never by importing
  // later HP, deck, RNG or rewards. Replanning only changes the test policy.
  if(const char*path=std::getenv("ALIGNMENT_PREFIX_TRACE")){
   json prefix;std::ifstream(path)>>prefix;const char*floorValue=std::getenv("ALIGNMENT_REPLAN_FLOOR");if(!floorValue)throw std::runtime_error("ALIGNMENT_REPLAN_FLOOR is required with a prefix");const int fromFloor=std::stoi(floorValue);
   if(prefix.at("seed").get<unsigned long long>()!=seed||prefix.at("controlled_fixture").get<bool>())throw std::runtime_error("prefix is not this natural seed");
   for(auto row:prefix.at("steps")){
    if(g.floorNum>=fromFloor)break;
    if(g.floorNum!=row.at("floor")||g.curHp!=row.at("hp"))throw std::runtime_error("recorded prefix state mismatch");
    if(g.screenState==ScreenState::BATTLE){BattleContext b;b.init(g);for(auto raw:row.at("actions")){search::Action action(static_cast<std::uint32_t>(raw.get<std::int64_t>()));if(!action.isValidAction(b))throw std::runtime_error("recorded combat action invalid");action.execute(b);}if(static_cast<int>(b.outcome)!=row.at("battle_outcome"))throw std::runtime_error("recorded combat outcome mismatch");b.exitBattle(g);}
    else for(auto raw:row.at("actions")){GameAction action(static_cast<std::uint32_t>(raw.get<std::int64_t>()));if(!action.isValidAction(g))throw std::runtime_error("recorded outside action invalid");action.execute(g);}
    result["steps"].push_back(row);
   }
   result["replayed_prefix"]=path;result["replan_floor"]=fromFloor;
  }
  int count=0;for(;count<1500 && g.outcome==GameOutcome::UNDECIDED;++count){
   const auto historyStart=agent.gameActionHistory.size();
   json row={{"floor",g.floorNum},{"act",g.act},{"screen",(int)g.screenState},{"hp",g.curHp},{"keys",{g.redKey,g.greenKey,g.blueKey}}};
   if(progress)progress<<row.dump()<<std::endl;
   if(g.screenState==ScreenState::BATTLE){
    BattleContext b;b.init(g);row["encounter"]=(int)g.info.encounter;row["monsters"]=json::array();for(int i=0;i<b.monsters.monsterCount;++i)row["monsters"].push_back(monsterIdStrings[(int)b.monsters.arr[i].id]);
    agent.playoutBattle(b);row["battle_outcome"]=(int)b.outcome;row["turns"]=b.turn+1;row["ending_hp"]=b.player.curHp;b.exitBattle(g);
   }else{
    const auto actions=GameAction::getAllActionsInState(g);if(actions.empty())throw std::runtime_error("no legal game action");for(auto a:actions)if(!a.isValidAction(g))throw std::runtime_error("enumerated illegal game action");
    GameAction action=actions.front();bool fixed=false;
    if(g.screenState==ScreenState::MAP_SCREEN){
     for(auto a:actions)if(!a.isPotionAction() && !g.greenKey && (!validation||g.act==3) && reaches(g,a.getIdx1(),g.curMapNodeY+1)){action=a;fixed=true;break;}
     if(!fixed&&validation){double best=-1000000;for(auto a:actions)if(!a.isPotionAction()){double score=routeScore(g,a.getIdx1(),g.curMapNodeY+1);if(score>best){best=score;action=a;fixed=true;}}}
     if(!fixed){for(auto a:actions)if(!a.isPotionAction()){action=a;fixed=true;break;}}
    }else if(g.screenState==ScreenState::REST_ROOM && !g.redKey && (!validation||(g.act==3&&g.curMapNodeY==14))){action=GameAction(2);fixed=true;}
    else if((validation||(safeRest&&g.act==3&&g.curMapNodeY==14))&&g.screenState==ScreenState::REST_ROOM){
     int desired=g.curHp<g.maxHp*.75&&!g.hasRelic(RelicId::COFFEE_DRIPPER)?0:1;
     GameAction candidate(desired);if(candidate.isValidAction(g)){action=candidate;fixed=true;}
    }
    else if(g.screenState==ScreenState::REWARDS){
     for(auto a:actions)if(a.getRewardsActionType()==GameAction::RewardsActionType::KEY && !a.isPotionAction()){action=a;fixed=true;break;}
     if(!fixed && controlled){action=GameAction(GameAction::RewardsActionType::SKIP);fixed=true;}
    }else if(controlled && g.screenState==ScreenState::TREASURE_ROOM){action=GameAction(0);fixed=true;}
    else if(controlled && g.screenState==ScreenState::BOSS_RELIC_REWARDS){action=GameAction(3);fixed=true;}
    else if(controlled && g.screenState==ScreenState::SHOP_ROOM){action=GameAction(GameAction::RewardsActionType::SKIP);fixed=true;}
    if(fixed){if(!action.isValidAction(g))throw std::runtime_error("chosen illegal game action");std::ostringstream s;action.printDesc(s,g);row["action"]=s.str();row["bits"]=action.bits;action.execute(g);}
    else{row["policy"]="existing ScumSearchAgent2";agent.stepOutOfCombatPolicy(g);}
   }
   row["actions"]=std::vector<int>(agent.gameActionHistory.begin()+historyStart,agent.gameActionHistory.end());
   if(row.contains("bits"))row["actions"].push_back(row["bits"]);
   result["steps"].push_back(row);
  }
  result["status"]=g.outcome==GameOutcome::PLAYER_VICTORY?"heart_victory":(g.outcome==GameOutcome::PLAYER_LOSS?"simulator_death":(g.outcome==GameOutcome::UNDECIDED?"truncated":"act3_only"));
 }catch(const std::exception&e){result["status"]="execution_error";result["error"]=e.what();}
 result["floor"]=g.floorNum;result["act"]=g.act;result["hp"]=g.curHp;result["keys"]={g.redKey,g.greenKey,g.blueKey};std::cout.rdbuf(outputBuffer);std::cout<<result.dump()<<'\n';return result["status"]=="execution_error"?1:0;
}
