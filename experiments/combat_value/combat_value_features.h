#pragma once
#include "combat/BattleContext.h"
#include <array>
#include <algorithm>
#include <cmath>

namespace combat_value {
constexpr int WIDTH = 512;
constexpr int HIDDEN = 32;
using Features = std::array<float, WIDTH>;
inline Features features(const sts::BattleContext &b) {
    using namespace sts;
    Features x{};
    const auto &p = b.player;
    const float raw[] = {
        p.curHp / 100.f, p.maxHp / 100.f, p.curHp / float(std::max(1,p.maxHp)),
        p.block / 100.f, p.strength / 20.f, p.dexterity / 10.f,
        p.energy / 5.f, p.energyPerTurn / 5.f, p.cardDrawPerTurn / 7.f,
        b.turn / 10.f, b.potionCount / 5.f, b.inputState == InputState::CARD_SELECT ? 1.f : 0.f,
        p.cardsPlayedThisTurn / 10.f, p.attacksPlayedThisTurn / 10.f, p.skillsPlayedThisTurn / 10.f,
        b.cards.cardsInHand / 10.f, b.cards.drawPile.size()/40.f, b.cards.discardPile.size()/40.f,
        b.cards.exhaustPile.size()/40.f, p.incenseBurnerCounter/6.f, p.penNibCounter/10.f,
        p.sundialCounter/3.f, p.nunchakuCounter/10.f, p.inkBottleCounter/10.f,
        p.happyFlowerCounter/3.f, b.monsters.monstersAlive/5.f, b.floorNum/60.f,
        b.cards.cardsInHand ? b.cards.handNormalityCount/3.f : 0.f,
        b.cards.handPainCount/3.f, b.cards.strikeCount/10.f, p.artifact/5.f, p.focus/10.f
    };
    std::copy(std::begin(raw), std::end(raw), x.begin());
    for (int s=1; s<=static_cast<int>(PS::THE_BOMB); ++s) {
        const auto status = static_cast<PS>(s);
        x[32+s] = p.statusMap.contains(status) ? p.statusMap.at(status)/10.f :
            (p.hasStatusRuntime(status) ? 1.f : 0.f);
    }
    for (int i=0; i<b.monsters.monsterCount; ++i) {
        const auto &m=b.monsters.arr[i];
        const int o=128+24*i;
        const auto damage = m.isAlive() ? m.getMoveBaseDamage(b) : DamageInfo{};
        const float v[] = {m.curHp/500.f,m.maxHp/500.f,m.curHp/float(std::max(1,m.maxHp)),
            m.block/100.f,m.strength/20.f,m.weak/5.f,m.vulnerable/5.f,m.artifact/5.f,
            m.uniquePower0/20.f,m.uniquePower1/200.f,m.miscInfo/5.f,
            m.isAlive()?1.f:0.f,m.halfDead?1.f:0.f,damage.damage/50.f,damage.attackCount/15.f,
            m.poison/20.f};
        std::copy(std::begin(v),std::end(v),x.begin()+o);
        x[o+16+(static_cast<unsigned>(m.moveHistory[0])*2654435761U)%8]=1.f;
    }
    x[248+static_cast<unsigned>(b.encounter)%8]=1.f;
    auto card = [&](const CardInstance &c, int zone) {
        const auto h=static_cast<unsigned>(c.id)*2654435761U;
        x[256+zone*64+((h^(h>>16))%64)]+=.2f;
        if (c.upgraded) x[256+zone*64+((h^(h>>11)^0x9e37U)%64)]+=.2f;
        if (zone==0) x[256+((h^(h>>9)^0x3c6eU)%64)]+=.05f*c.costForTurn;
    };
    for(int i=0;i<b.cards.cardsInHand;++i) card(b.cards.hand[i],0);
    for(const auto &c:b.cards.drawPile) card(c,1);
    for(const auto &c:b.cards.discardPile) card(c,2);
    for(const auto &c:b.cards.exhaustPile) card(c,3);
    for(auto &v:x) v=std::clamp(v,-10.f,10.f);
    return x;
}
}
