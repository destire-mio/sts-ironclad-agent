// Read-only structure audit of the unchanged E121 MCTS tree.
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <unordered_map>
#include <type_traits>
#include <iterator>
#include "combat/BattleContext.h"
#include "sim/search/BattleScumSearcher2.h"

namespace py=pybind11;
using namespace sts;

struct Key {
    std::string bytes;
    template<class T> void scalar(const T &value) {
        static_assert(std::is_arithmetic_v<T> || std::is_enum_v<T>);
        bytes.append(reinterpret_cast<const char*>(&value),sizeof(value));
    }
    template<class T> void scalars(const T &values) {
        scalar(std::uint64_t(std::size(values))); for(const auto &v:values) scalar(v);
    }
    void rng(const Random &r) { scalar(r.counter);scalar(r.seed0);scalar(r.seed1); }
    void card(const CardInstance &c) {
#define F(name) scalar(c.name)
        F(id);F(uniqueId);F(specialData);F(cost);F(costForTurn);F(upgraded);F(freeToPlayOnce);F(retain);
#undef F
    }
    template<class T> void cards(const T &values) {
        scalar(std::uint64_t(values.size()));for(const auto &c:values)card(c);
    }
    void player(const Player &p) {
#define F(name) scalar(p.name)
        F(cc);F(gold);F(curHp);F(maxHp);F(energy);F(energyPerTurn);F(cardDrawPerTurn);
        F(stance);F(orbSlots);F(lastTargetedMonster);F(block);F(artifact);F(dexterity);F(focus);F(strength);
        F(justAppliedBits);F(statusBits0);F(statusBits1);
        scalar(std::uint64_t(p.statusMap.size()));for(auto [s,v]:p.statusMap){scalar(s);scalar(v);}
        scalar(std::uint64_t(p.powerOrder.size()));for(const auto &v:p.powerOrder){scalar(v.status);scalar(v.bombId);}
        F(relicBits0);F(relicBits1);scalars(p.cardUseRelics);
        F(happyFlowerCounter);F(incenseBurnerCounter);F(inkBottleCounter);F(inserterCounter);
        F(nunchakuCounter);F(penNibCounter);F(sundialCounter);F(haveUsedNecronomiconThisTurn);
        F(combustHpLoss);F(devaFormEnergyPerTurn);F(echoFormCardsDoubled);F(panacheCounter);
        F(cardsPlayedThisTurn);F(attacksPlayedThisTurn);F(skillsPlayedThisTurn);
        scalar(p.orangePelletsCardTypesPlayed.to_ullong());F(cardsDiscardedThisTurn);
        F(lastAttackUnblockedDamage);F(timesDamagedThisCombat);
        scalar(std::uint64_t(p.bombs.size()));for(const auto &v:p.bombs){scalar(v.id);scalar(v.turns);scalar(v.damage);}
        F(nextBombId);
#undef F
    }
    void monster(const Monster &m) {
#define F(name) scalar(m.name)
        F(idx);F(id);F(curHp);F(maxHp);F(block);F(isEscapingB);F(halfDead);F(escapeNext);
        scalars(m.moveHistory);F(statusBits);F(artifact);F(blockReturn);F(choked);F(corpseExplosion);
        F(lockOn);F(mark);F(metallicize);F(platedArmor);F(poison);F(regen);F(shackled);
        F(strength);F(vulnerable);F(weak);F(uniquePower0);F(uniquePower1);F(miscInfo);
#undef F
    }
    void queuedCard(const CardQueueItem &q) {
#define F(name) scalar(q.name)
        card(q.card);F(target);F(isEndTurn);F(triggerOnUse);F(ignoreEnergyTotal);F(energyOnUse);
        F(freeToPlay);F(randomTarget);F(autoplay);F(regretCardCount);F(purgeOnUse);F(exhaustOnUse);
#undef F
    }
    void selection(const CardSelectInfo &c) {
#define F(name) scalar(c.name)
        scalars(c.cards);F(canPickZero);F(canPickAnyNumber);F(pickCount);F(data0);
        F(discoveryZeroCost);F(discoveryFrameRng);F(discoveryType);scalars(c.selectedIndices);F(cardSelectTask);
#undef F
    }
    void manager(const CardManager &c) {
#define F(name) scalar(c.name)
        F(nextUniqueCardId);F(cardsInHand);
        // Preserve even stale inactive slots and limbo for this conservative
        // diagnostic. Unequal keys therefore do not prove semantic inequality.
        cards(c.hand);cards(c.limbo);cards(c.stasisCards);cards(c.drawPile);cards(c.discardPile);cards(c.exhaustPile);
        F(handNormalityCount);F(handPainCount);F(strikeCount);F(handBloodCardCount);
        F(drawPileBloodCardCount);F(discardPileBloodCardCount);
#undef F
    }
    explicit Key(const BattleContext &b) {
#define F(name) scalar(b.name)
        F(haveUsedDiscoveryAction);F(actionFrameDelta);F(undefinedBehaviorEvoked);
        F(seed);F(floorNum);F(encounter);F(loopCount);F(energyWasted);F(cardsDrawn);
        rng(b.aiRng);rng(b.cardRandomRng);rng(b.miscRng);rng(b.monsterHpRng);rng(b.potionRng);rng(b.shuffleRng);
        F(ascension);F(outcome);F(inputState);selection(b.cardSelectInfo);F(monsterTurnIdx);
        F(isBattleOver);F(endTurnQueued);F(turnHasEnded);F(skipMonsterTurn);
        // Both queues are empty at admitted states. Stale callables, storage
        // addresses, capacities and circular-buffer positions cannot be read
        // before a subsequent insertion. They are not future game state.
        F(potionCount);F(potionCapacity);scalars(b.potions);F(turn);player(b.player);
        scalar(b.monsters.monstersAlive);scalar(b.monsters.monsterCount);
        scalar(b.monsters.extraRollMoveOnTurn.to_ullong());scalar(b.monsters.skipTurn.to_ullong());
        for(const auto &m:b.monsters.arr)monster(m);
        manager(b.cards);queuedCard(b.curCardQueueItem);scalar(b.miscBits.to_ullong());
#undef F
    }
};

static bool admitted(const BattleContext &b) {
    return b.outcome==Outcome::UNDECIDED && b.inputState==InputState::PLAYER_NORMAL
        && b.actionQueue.isEmpty() && b.cardQueue.isEmpty();
}

static py::object key(const BattleContext &b) {
    if(!admitted(b))return py::none();
    return py::bytes(Key(b).bytes);
}

static py::dict coverage(const BattleContext &original) {
    if(!admitted(original))throw std::invalid_argument("coverage needs a settled player state");
    const auto baseline=Key(original).bytes;
    py::dict out;
    const auto test=[&](const char *name, auto change) {
        auto copy=original;change(copy);out[name]=baseline!=Key(copy).bytes;
    };
    test("rng_seed",[](auto &b){b.shuffleRng.seed0^=1;});
    test("rng_counter",[](auto &b){++b.shuffleRng.counter;});
    test("HP",[](auto &b){++b.player.curHp;});
    test("relic_counter",[](auto &b){++b.player.incenseBurnerCounter;});
    test("enemy_hidden_power",[](auto &b){++b.monsters.arr[0].uniquePower1;});
    test("card_identity",[](auto &b){++b.cards.hand[0].uniqueId;});
    test("inactive_card_slot",[](auto &b){++b.cards.limbo[9].specialData;});
    test("power_order",[](auto &b){b.player.powerOrder.push_back({PlayerStatus::STRENGTH,-1});});
    test("discard_order",[](auto &b){
        b.cards.discardPile.clear();auto a=b.cards.hand[0];auto c=a;c.uniqueId+=20;
        b.cards.discardPile.push_back(a);b.cards.discardPile.push_back(c);
    });
    auto a=original,c=original;
    a.cards.discardPile.clear();auto x=a.cards.hand[0],y=x;y.uniqueId+=20;
    a.cards.discardPile.push_back(x);a.cards.discardPile.push_back(y);c=a;
    std::swap(c.cards.discardPile[0],c.cards.discardPile[1]);
    out["same_inventory_different_discard_order"]=Key(a).bytes!=Key(c).bytes;
    a=original;a.inputState=InputState::CARD_SELECT;out["pending_selection_rejected"]=!admitted(a);
    a=original;a.actionQueue.pushBack(Action([](BattleContext&){}));out["pending_callback_rejected"]=!admitted(a);
    return out;
}

static BattleContext shiftedEmptyQueues(const BattleContext &b) {
    if(!admitted(b))throw std::invalid_argument("empty queues required");
    auto c=b;const int capacity=c.actionQueue.getCapacity();
    c.actionQueue.front=(c.actionQueue.front+1)%capacity;c.actionQueue.back=(c.actionQueue.back+1)%capacity;
    c.cardQueue.frontIdx=(c.cardQueue.frontIdx+1)%CardQueue::capacity;
    c.cardQueue.backIdx=(c.cardQueue.backIdx+1)%CardQueue::capacity;
    return c;
}

static py::dict profile(const BattleContext &root, int budget) {
    if(budget<=0)throw std::invalid_argument("positive budget required");
    search::BattleScumSearcher2 search(root);search.search(budget);
    struct Frame { const search::BattleScumSearcher2::Node *node;BattleContext state;std::vector<std::uint32_t> path; };
    std::vector<Frame> stack;stack.push_back({&search.root,root,{}});
    struct Seen {std::vector<std::uint32_t> path;std::int64_t visits;};
    std::unordered_map<std::string,Seen> seen;
    py::list witnesses;std::int64_t nodes=0,settled=0,duplicate=0,edges=0,visits=0,duplicateVisits=0;
    std::int64_t keyBytes=0;
    while(!stack.empty()) {
        auto frame=std::move(stack.back());stack.pop_back();++nodes;visits+=frame.node->simulationCount;
        if(admitted(frame.state)) {
            ++settled;auto payload=Key(frame.state).bytes;keyBytes+=payload.size();
            auto found=seen.find(payload);
            if(found==seen.end())seen.emplace(std::move(payload),Seen{frame.path,frame.node->simulationCount});
            else {
                ++duplicate;duplicateVisits+=frame.node->simulationCount;
                if(py::len(witnesses)<8) {
                    py::dict witness;witness["first"]=found->second.path;witness["second"]=frame.path;
                    witness["turn"]=frame.state.turn;witness["key"]=py::bytes(payload);witnesses.append(witness);
                }
            }
        }
        for(const auto &edge:frame.node->edges) {
            if(edge.node.simulationCount==0)continue;
            auto child=frame.state;
            if(!edge.action.isValidAction(child))throw std::runtime_error("tree contains invalid action");
            edge.action.execute(child);auto path=frame.path;path.push_back(edge.action.bits);
            stack.push_back({&edge.node,std::move(child),std::move(path)});++edges;
        }
    }
    py::dict out;out["nodes"]=nodes;out["settled_nodes"]=settled;out["duplicate_nodes"]=duplicate;
    out["unique_settled_keys"]=seen.size();out["replayed_tree_edges"]=edges;
    out["sum_node_visits"]=visits;out["sum_duplicate_visits"]=duplicateVisits;
    out["serialized_key_bytes"]=keyBytes;out["simulations"]=search.root.simulationCount;
    out["best_actions"]=search.bestActionSequence;out["best_hp"]=search.outcomePlayerHp;
    out["best_value"]=search.bestActionValue;out["witnesses"]=witnesses;
    search::Action recommended(search::ActionType::END_TURN);
    if(search.outcomePlayerHp>0 && !search.bestActionSequence.empty())recommended=search.bestActionSequence.front();
    else {std::int64_t best=-1;for(const auto &edge:search.root.edges)if(edge.node.simulationCount>best){best=edge.node.simulationCount;recommended=edge.action;}}
    out["recommended"]=recommended.bits;
    return out;
}

PYBIND11_MODULE(heart_search_structure,m) {
    m.def("key",&key);m.def("coverage",&coverage);m.def("shifted_empty_queues",&shiftedEmptyQueues);
    m.def("profile",&profile);
}
