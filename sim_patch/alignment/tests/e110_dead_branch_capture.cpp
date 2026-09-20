#include "combat/BattleContext.h"
#include "game/Game.h"
#include "game/GameContext.h"
#include "sim/search/Action.h"
#include <array>
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>
using namespace sts;
static void check(bool ok,const char *why) { if(!ok) throw std::runtime_error(why); }
static std::array<Random,6> rngs(const BattleContext &b) { return {b.aiRng,b.cardRandomRng,b.miscRng,b.monsterHpRng,b.potionRng,b.shuffleRng}; }
static Random generates(CardId id) {
    for(int seed=0;seed<4096;++seed) { Random r(seed),copy=r; if(getTrulyRandomCardInCombat(copy,CharacterClass::IRONCLAD)==id) return r; }
    throw std::runtime_error("fixture card not found");
}
static BattleContext fixture(bool heart,bool branch,int hits,CardId generated) {
    GameContext g(CharacterClass::IRONCLAD,123,20); if(branch)g.obtainRelic(R::DEAD_BRANCH);
    BattleContext b;b.init(g,heart?MonsterEncounter::THE_HEART:MonsterEncounter::CULTIST);
    b.cards=CardManager();b.player.energy=3;b.player.curHp=60;b.player.maxHp=80;b.player.block=0;
    b.player.timesDamagedThisCombat=hits;b.cardRandomRng=generates(generated);
    b.cards.createTempCardInHand(CardInstance(CardId::INTIMIDATE));return b;
}
static void play(BattleContext &b) {
    search::Action a(search::ActionType::CARD,0,0);check(a.isValidAction(b),"registered card action is illegal");a.execute(b);
    check(b.inputState==InputState::PLAYER_NORMAL&&b.actionQueue.isEmpty()&&b.cardQueue.isEmpty(),"card action did not settle");
}
static void sameRng(const BattleContext &a,const BattleContext &b) {
    auto left=rngs(a),right=rngs(b);for(int i=0;i<6;++i)check(left[i].counter==right[i].counter&&left[i].randomLong()==right[i].randomLong(),"copied branch RNG differs");
}
int main(int argc,char**argv) {
    const std::string name=argc>1?argv[1]:"";
    bool heart=name!="no_heart",branch=name!="no_branch",blocked=name=="blocked";
    int hits=name=="zero_history"?0:(name=="saturated"?5:3);
    CardId generated=name=="other_card"?CardId::HEMOKINESIS:CardId::BLOOD_FOR_BLOOD;
    check(name=="zero_history"||name=="prior_history"||name=="existing_card"||name=="sibling_copy"||name=="no_heart"||name=="blocked"||name=="saturated"||name=="other_card"||name=="no_branch","unknown E110 case");
    auto b=fixture(heart,branch,hits,generated);if(blocked)b.player.block=2;
    if(name=="existing_card")b.cards.createTempCardInHand(b.createGeneratedCard(CardId::BLOOD_FOR_BLOOD));
    const auto untouched=b;auto sibling=b;auto expectedRng=b.cardRandomRng;
    if(branch)check(getTrulyRandomCardInCombat(expectedRng,CharacterClass::IRONCLAD)==generated,"unexpected generated fixture card");
    play(b);
    const bool lostHp=heart&&!blocked;
    check(b.player.timesDamagedThisCombat==hits+int(lostHp)&&b.player.curHp==60-(lostHp?2:0),"actual HP-loss count changed");
    check(b.cards.exhaustPile.size()==1&&b.cards.exhaustPile[0].id==CardId::INTIMIDATE,"played card destination differs");
    check(b.cards.cardsInHand==int(branch)+int(name=="existing_card"),"generated hand size differs");
    if(branch) {
        const auto &c=b.cards.hand[b.cards.cardsInHand-1];
        const int cost=generated==CardId::BLOOD_FOR_BLOOD?std::max(0,4-hits):1;
        check(c.id==generated&&c.cost==cost&&c.costForTurn==cost,"Dead Branch used insertion-time HP history instead of creation-time cost");
    }
    if(name=="existing_card")check(b.cards.hand[0].cost==0&&b.cards.hand[0].costForTurn==0,"already present Blood for Blood did not receive the intervening damage");
    auto actualRng=b.cardRandomRng;check(actualRng.counter==expectedRng.counter&&actualRng.randomLong()==expectedRng.randomLong(),"generation consumed different card RNG");
    check(sibling.player.curHp==60&&sibling.player.timesDamagedThisCombat==hits&&sibling.cards.hand[0].id==CardId::INTIMIDATE,"executing one branch mutated a sibling");sameRng(sibling,untouched);
    if(name=="sibling_copy") {play(sibling);check(sibling.cards.hand[0].cost==b.cards.hand[0].cost&&sibling.cards.hand[0].id==b.cards.hand[0].id,"copied execution changed generated card");sameRng(b,sibling);}
    std::cout<<name<<" passed\n";
}
