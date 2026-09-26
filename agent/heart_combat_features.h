// Public battle features for a value model; no RNG, seed or draw-pile order.
#pragma once
#include <algorithm>
#include <cmath>
#include <iterator>
#include <vector>
#include "combat/BattleContext.h"
#include "constants/Relics.h"

namespace combat_value {
using namespace sts;
using Sparse=std::vector<std::pair<int,float>>;
constexpr int CARD_COUNT=std::size(cardEnumStrings);
constexpr int MONSTER_COUNT=std::size(monsterIdStrings);
constexpr int STATUS_COUNT=static_cast<int>(PS::THE_BOMB)+1;
constexpr int ENEMY_STATUS_COUNT=static_cast<int>(MS::INVALID);
constexpr int POTION_COUNT=std::size(potionNames);

struct Builder {
    Sparse values;int offset=0;
    Builder(){values.reserve(256);}
    void scalar(float value) {
        value=std::clamp(value,-5.f,5.f);
        if(value!=0)values.emplace_back(offset,value);++offset;
    }
    void category(int id,int count) {
        if(id>=0 && id<count)values.emplace_back(offset+id,1.f);offset+=count;
    }
    template<class Sequence> void pile(const Sequence &cards,bool hand) {
        const int channels=hand?5:3;std::vector<float> block(channels*CARD_COUNT,0.f);
        for(const auto &card:cards) {
            const int id=static_cast<int>(card.id);if(id<=0 || id>=CARD_COUNT)continue;
            block[id]+=.25f;block[CARD_COUNT+id]+=card.getUpgradeCount()*.25f;
            block[2*CARD_COUNT+id]+=card.specialData*.05f;
            if(hand){block[3*CARD_COUNT+id]+=card.costForTurn*.125f;block[4*CARD_COUNT+id]+=card.freeToPlayOnce*.25f;}
        }
        for(float v:block)scalar(v);
    }
};

inline Builder features(const BattleContext &b) {
    Builder f;const auto &p=b.player;
    const auto s=[&](float value,float scale=1.f){f.scalar(value/scale);};
    s(p.curHp,100);s(p.maxHp,100);s(p.curHp,std::max(1,p.maxHp));s(p.block,100);
    s(p.energy,10);s(p.energyPerTurn,10);s(p.cardDrawPerTurn,10);s(p.gold,500);
    s(p.strength,20);s(p.dexterity,20);s(p.focus,20);s(p.artifact,10);s(b.turn,20);
    s(b.potionCount,5);s(b.potionCapacity,5);s(p.lastTargetedMonster,5);
    s(p.cardsPlayedThisTurn,20);s(p.attacksPlayedThisTurn,20);s(p.skillsPlayedThisTurn,20);s(p.cardsDiscardedThisTurn,20);
    s(p.happyFlowerCounter,3);s(p.incenseBurnerCounter,6);s(p.inkBottleCounter,10);
    s(p.nunchakuCounter,10);s(p.penNibCounter,10);s(p.sundialCounter,3);
    s(p.haveUsedNecronomiconThisTurn);s(p.panacheCounter,5);s(p.combustHpLoss,10);
    s(p.echoFormCardsDoubled,10);s(p.devaFormEnergyPerTurn,10);s(p.orangePelletsCardTypesPlayed.to_ulong(),7);
    f.category(static_cast<int>(p.stance),4);
    for(int id=1;id<STATUS_COUNT;++id) {
        const auto status=static_cast<PS>(id);s(p.hasStatusRuntime(status));
        const auto item=p.statusMap.find(status);s(item==p.statusMap.end()?0:item->second,20);
        float position=0;for(int j=0;j<static_cast<int>(p.powerOrder.size());++j)
            if(p.powerOrder[j].status==status)position+=(j+1)/32.f;
        s(position);
    }
    for(int id=0;id<128;++id) {
        s(p.hasRelicRuntime(static_cast<RelicId>(id)));
        float position=0;for(int j=0;j<p.cardUseRelics.size();++j)if(static_cast<int>(p.cardUseRelics[j])==id)position=(j+1)/12.f;
        s(position);
    }
    for(int countdown=1;countdown<=3;++countdown) {
        int count=0,damage=0;for(const auto &bomb:p.bombs)if(bomb.turns==countdown){++count;damage+=bomb.damage;}
        s(count,5);s(damage,100);
    }
    std::vector<float> potions(POTION_COUNT,0.f);
    for(int j=0;j<b.potionCapacity;++j){int id=static_cast<int>(b.potions[j]);if(id>=0 && id<POTION_COUNT)potions[id]+=.2f;}
    for(float v:potions)s(v);
    const bool dome=p.hasRelic<RelicId::RUNIC_DOME>();s(dome);
    for(int j=0;j<5;++j) {
        const auto &m=b.monsters.arr[j];const bool present=j<b.monsters.monsterCount && m.id!=MonsterId::INVALID;
        f.category(present?static_cast<int>(m.id):-1,MONSTER_COUNT);
        s(present?m.curHp:0,200);s(present?m.maxHp:0,200);s(present?m.block:0,100);
        s(present && m.isAlive());s(present && m.isTargetable());s(present && m.halfDead);
        const bool visible=present && !dome && m.moveHistory[0]!=MMID::INVALID;
        DamageInfo damage;if(visible)damage=m.getMoveBaseDamage(b);else damage={0,0};
        s(visible);s(visible && m.isAttacking());s(damage.damage,100);s(damage.attackCount,10);
        for(int id=0;id<ENEMY_STATUS_COUNT;++id) {
            const auto status=static_cast<MS>(id);const bool has=present && m.hasStatusInternal(status);
            s(has);s(has?m.getStatusInternal(status):0,20);
        }
    }
    std::vector<CardInstance> hand(b.cards.hand.begin(),b.cards.hand.begin()+b.cards.cardsInHand);
    f.pile(hand,true);f.pile(b.cards.drawPile,false);f.pile(b.cards.discardPile,false);
    f.pile(b.cards.exhaustPile,false);f.pile(b.cards.stasisCards,false);
    const bool selection=b.inputState==InputState::CARD_SELECT;
    s(selection);f.category(selection?static_cast<int>(b.cardSelectInfo.cardSelectTask):-1,
                            static_cast<int>(CardSelectTask::WARCRY)+1);
    f.category(selection?static_cast<int>(b.curCardQueueItem.card.id):-1,CARD_COUNT);
    s(selection?b.cardSelectInfo.pickCount:0,10);s(selection && b.cardSelectInfo.canPickZero);
    s(selection && b.cardSelectInfo.canPickAnyNumber);s(selection?b.cardSelectInfo.selectedIndices.size():0,10);
    std::vector<float> offered(CARD_COUNT,0.f);
    if(selection && (b.cardSelectInfo.cardSelectTask==CardSelectTask::DISCOVERY || b.cardSelectInfo.cardSelectTask==CardSelectTask::CODEX))
        for(auto card:b.cardSelectInfo.cards){const int id=static_cast<int>(card);if(id>0 && id<CARD_COUNT)offered[id]+=1.f/3;}
    for(float v:offered)s(v);
    return f;
}

inline float quality(double nativeValue,const BattleContext &state) {
    const double maximum=100.*(35+std::max(1,state.player.maxHp)+4*state.potionCapacity);
    return static_cast<float>(std::clamp(nativeValue/maximum,0.,1.));
}
}
