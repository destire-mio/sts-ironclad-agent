//
// Created by keega on 9/18/2021.
//

#include "sim/search/BattleScumSearcher2.h"
#include "sim/search/ExpertKnowledge.h"

#include <utility>
#include <string>
#include <memory>
#include <stdexcept>
#include <type_traits>

using namespace sts;

std::int64_t simulationIdx = 0; // for debugging

namespace sts::search {
    thread_local search::BattleScumSearcher2 *g_debug_scum_search;
    template<class NodeLike> void enumerateActionsImpl(NodeLike &, const BattleContext &, bool preservePotions);
    template<class NodeLike> void enumerateCardActionsImpl(NodeLike &, const BattleContext &);
    template<class NodeLike> void enumeratePotionActionsImpl(NodeLike &, const BattleContext &, bool preservePotions);
    template<class NodeLike> void enumerateCardSelectActionsImpl(NodeLike &, const BattleContext &);
}

search::BattleScumSearcher2::Edge *search::BattleScumSearcher2::EdgeRange::begin() { return data; }
const search::BattleScumSearcher2::Edge *search::BattleScumSearcher2::EdgeRange::begin() const { return data; }
search::BattleScumSearcher2::Edge *search::BattleScumSearcher2::EdgeRange::end() { return count ? data + count : data; }
const search::BattleScumSearcher2::Edge *search::BattleScumSearcher2::EdgeRange::end() const { return count ? data + count : data; }
search::BattleScumSearcher2::Edge &search::BattleScumSearcher2::EdgeRange::operator[](std::size_t index) {
    assert(index < count); return data[index];
}
const search::BattleScumSearcher2::Edge &search::BattleScumSearcher2::EdgeRange::operator[](std::size_t index) const {
    assert(index < count); return data[index];
}

search::BattleScumSearcher2::Edge *search::BattleScumSearcher2::EdgeArena::allocate(std::size_t count) {
    static_assert(std::is_trivially_destructible_v<Edge>);
    if (count == 0) return nullptr;
    if (count > std::numeric_limits<std::uint32_t>::max())
        throw std::length_error("too many search actions");
    if (blocks.empty() || blocks.back().capacity - blocks.back().used < count) {
        const auto ordinary = blocks.empty() ? std::size_t{256}
            : std::min(std::size_t{4096}, blocks.back().capacity * 2);
        const auto capacity = std::max(count, ordinary);
        // Build the complete block before publishing it. Its allocation never
        // moves when the small vector of block owners grows.
        auto data = std::make_unique<Edge[]>(capacity);
        blocks.push_back({std::move(data), capacity, 0});
    }
    auto &block = blocks.back();
    auto *result = block.data.get() + block.used;
    block.used += count;
    return result;
}

std::size_t search::BattleScumSearcher2::EdgeArena::storageBytes() const {
    std::size_t bytes = 0;
    for (const auto &block : blocks) bytes += block.capacity * sizeof(Edge);
    return bytes;
}

void search::BattleScumSearcher2::appendActions(Node &node, const std::vector<RolloutNode::Edge> &actions) {
    if (actions.empty()) return;
    const auto oldSize = node.edges.size();
    const auto size = oldSize + actions.size();
    auto *edges = edgeArena.allocate(size);
    if (oldSize) std::copy(node.edges.begin(), node.edges.end(), edges);
    for (std::size_t i = 0; i < actions.size(); ++i) edges[oldSize + i].action = actions[i].action;
    node.edges = {edges, static_cast<std::uint32_t>(size)};
}

void search::BattleScumSearcher2::retainSubtree(const Node &node) {
    if (prefixCaching) throw std::logic_error("cannot replace a tree during search");
    EdgeArena retained;
    Node next = node;
    std::vector<Node *> pending{&next};
    while (!pending.empty()) {
        auto &parent = *pending.back();
        pending.pop_back();
        if (parent.edges.empty()) continue;
        const auto size = parent.edges.size();
        auto *children = retained.allocate(size);
        std::copy(parent.edges.begin(), parent.edges.end(), children);
        parent.edges = {children, static_cast<std::uint32_t>(size)};
        for (auto &edge : parent.edges)
            if (!edge.node.edges.empty()) pending.push_back(&edge.node);
    }
    // All copies succeeded: commit before releasing the old, unrelated tree.
    // Search-scoped caches have expired, and their raw node tags cannot escape.
    searchStack.clear();
    root = next;
    edgeArena = std::move(retained);
}



search::BattleScumSearcher2::BattleScumSearcher2(const BattleContext &bc, search::EvalFnc _evalFnc)
    : rootState(new BattleContext(bc)), evalFnc(std::move(_evalFnc)), randGen(bc.seed+bc.floorNum) {
    bestActionValue = std::numeric_limits<double>::lowest();
}

void search::BattleScumSearcher2::search(int64_t simulations) {
    g_debug_scum_search = this;
    // Root addresses may be reused after re-rooting. Bound snapshots to this
    // call, including early returns and exceptions; direct step() calls copy
    // the current root instead of borrowing an expired snapshot.
    struct PrefixScope {
        BattleScumSearcher2 &searcher;
        explicit PrefixScope(BattleScumSearcher2 &s) : searcher(s) {
            s.prefixStates.clear();
            s.prefixStates.resize(32);
            s.deeperPrefixStates.clear();
            s.deeperPrefixStates.resize(256);
            s.prefixCaching = true;
        }
        ~PrefixScope() {
            searcher.prefixCaching = false;
            searcher.prefixStates.clear();
            searcher.deeperPrefixStates.clear();
        }
    } prefixScope(*this);

    if (isTerminalState(*rootState)) {
        auto evaluation = combat4rEnabled ? evaluateEndState4r(*rootState, combatInitialMaxHp) :
            combat4qEnabled ? evaluateEndState4q(*rootState) : evaluateEndState(*rootState);
        outcomePlayerHp = rootState->outcome == Outcome::UNDECIDED ? -1 : rootState->player.curHp;
        bestActionSequence = {};

        root.evaluationSum = evaluation;
        root.simulationCount = 1;
        return;
    }

    for (std::int64_t simCount = 0; simCount < simulations; ++simCount) {
        step();
    }
}

void search::BattleScumSearcher2::step() {
    searchStack = {&root};
    actionStack.clear();
    int firstEdge = -1;

    // Selection depends only on tree statistics. Defer deterministic state
    // transitions until a new leaf actually needs a simulation. Revisited
    // terminal paths reuse their exact evaluation without consuming RNG.
    while (!searchStack.back()->edges.empty()) {
        auto &node = *searchStack.back();
        const int selected = selectBestEdgeToSearch(node);
        if (searchStack.size() == 1) firstEdge = selected;
        auto &edge = node.edges[selected];
        actionStack.push_back(edge.action);
        searchStack.push_back(&edge.node);
    }
    auto &leaf = *searchStack.back();
    if (leaf.terminalHp != -2) {
        updateFromEvaluation(searchStack, actionStack, leaf.evaluationSum, leaf.terminalHp);
        return;
    }

    constexpr std::size_t checkpointDepth = 2;
    PrefixSnapshot *checkpoint = nullptr;
    const Node *checkpointNode = nullptr;
    if (prefixCaching && actionStack.size() >= checkpointDepth) {
        checkpointNode = searchStack[checkpointDepth];
        const auto address = reinterpret_cast<std::uintptr_t>(checkpointNode);
        checkpoint = &deeperPrefixStates[((address >> 4) ^ (address >> 13)) & 255];
    }
    std::size_t skipped = 0;
    BattleContext state = [&]() {
        if (checkpoint && checkpoint->node == checkpointNode) {
            skipped = checkpointDepth;
            return BattleContext(*checkpoint->state);
        }
        if (!prefixCaching || firstEdge < 0 || firstEdge >= 32)
            return BattleContext(*rootState);
        auto &cached = prefixStates[firstEdge];
        if (!cached) {
            auto next = std::make_unique<BattleContext>(*rootState);
            actionStack.front().execute(*next);
            cached = std::move(next);
        }
        skipped = 1;
        return BattleContext(*cached);
    }();
    if (checkpoint && skipped < checkpointDepth) {
        for (; skipped < checkpointDepth; ++skipped) actionStack[skipped].execute(state);
        // Allocate the complete snapshot before publishing its identity.
        auto snapshot = std::make_unique<BattleContext>(state);
        checkpoint->state = std::move(snapshot);
        checkpoint->node = checkpointNode;
    }
    for (std::size_t i=skipped; i<actionStack.size(); ++i) actionStack[i].execute(state);
    if (isTerminalState(state)) {
        updateFromPlayout(searchStack, actionStack, state);
        return;
    }
    ++simulationIdx;
    enumerateActionsForNode(leaf, state);
    auto &edge = leaf.edges[selectFirstActionForLeafNode(leaf)];
    edge.action.execute(state);
    actionStack.push_back(edge.action);
    searchStack.push_back(&edge.node);
    playoutRandom(state, actionStack);
    updateFromPlayout(searchStack, actionStack, state);
}

void search::BattleScumSearcher2::updateFromPlayout(const std::vector<Node *> &stack, const std::vector<Action> &actionStack, const BattleContext &endState) {
    const auto evaluation = combat4rEnabled ? evaluateEndState4r(endState, combatInitialMaxHp) :
        combat4qEnabled ? evaluateEndState4q(endState) : evaluateEndState(endState);
    const int terminalHp = endState.outcome == Outcome::UNDECIDED ? -1 : endState.player.curHp;
    // Only cache a terminal reached by tree edges, not a random continuation
    // whose start node may have many other possible outcomes.
    if (actionStack.size() + 1 == stack.size()) stack.back()->terminalHp = terminalHp;
    updateFromEvaluation(stack, actionStack, evaluation, terminalHp);
}

void search::BattleScumSearcher2::updateFromEvaluation(const std::vector<Node *> &stack,
        const std::vector<Action> &actionStack, double evaluation, int terminalHp) {
    if (evaluation > bestActionValue) {
        bestActionSequence = actionStack;
        bestActionValue = evaluation;
        outcomePlayerHp = terminalHp;
    }

    if (evaluation < minActionValue) {
        minActionValue = evaluation;
    }

    for (auto it = stack.rbegin(); it != stack.rend(); ++it) {
        auto &node = *(*it);
        // Retain the best sampled continuation for deterministic planning.
        node.evaluationSum = node.simulationCount == 0
            ? evaluation : std::max(node.evaluationSum, evaluation);
        ++node.simulationCount;
    }
}

bool search::BattleScumSearcher2::isTerminalState(const BattleContext &bc) const { // maybe can optimize by making this evaluate directly if score cannot possibly be higher than best
    // A random rollout can exhaust all attacks and enter a real stalemate.
    // End that search branch before the executor's safety limit is reached.
    return bc.outcome != Outcome::UNDECIDED || bc.turn >= 500;
}

double search::BattleScumSearcher2::evaluateEdge(const search::BattleScumSearcher2::Node &parent, int edgeIdx) {

    const auto &edge = parent.edges[edgeIdx];

    // Visit every legal edge before applying a finite confidence score.
    if (edge.node.simulationCount == 0) return std::numeric_limits<double>::infinity();
    double qualityValue = 0.0;
    const double evalRange = bestActionValue - minActionValue;
    if (std::isfinite(evalRange) && evalRange > 0.0) {
        const double bestReturn = edge.node.evaluationSum;
        qualityValue = (bestReturn - minActionValue) / evalRange;
    }
    // Identical returns carry no preference; avoid 0/0 and use exploration.
    const double explorationValue = explorationParameter *
        std::sqrt(std::log(parent.simulationCount + 1) / edge.node.simulationCount);

    return qualityValue + explorationValue;
}

int search::BattleScumSearcher2::selectBestEdgeToSearch(const search::BattleScumSearcher2::Node &cur) {
    if (cur.edges.size() == 1) {
        return 0;
    }

    // An unvisited edge has infinite priority; preserve the original tie order.
    for (int i = 0; i < static_cast<int>(cur.edges.size()); ++i) {
        if (cur.edges[i].node.simulationCount == 0) return i;
    }
    const double parentLog = std::log(cur.simulationCount + 1);
    const double evalRange = bestActionValue - minActionValue;
    const bool usableRange = std::isfinite(evalRange) && evalRange > 0.0;
    const auto score = [&](const Node &child) {
        const double quality = usableRange ? (child.evaluationSum - minActionValue) / evalRange : 0.0;
        // Match the original two floating-point expressions. Combining this
        // into one return expression permits FMA contraction and changes ties.
        const double exploration = explorationParameter * std::sqrt(parentLog / child.simulationCount);
        return quality + exploration;
    };
    int bestEdge = 0;
    double bestEdgeValue = score(cur.edges[0].node);
    for (int i = 1; i < static_cast<int>(cur.edges.size()); ++i) {
        const double value = score(cur.edges[i].node);
        if (value > bestEdgeValue) {
            bestEdge = i;
            bestEdgeValue = value;
        }
    }
    return bestEdge;
}

int search::BattleScumSearcher2::selectFirstActionForLeafNode(const search::BattleScumSearcher2::Node &leafNode) {
    auto dist = std::uniform_int_distribution<int>(0, static_cast<int>(leafNode.edges.size())-1);
    return dist(randGen);
}

void search::BattleScumSearcher2::playoutRandom(BattleContext &state, std::vector<Action> &actionStack) {
    auto &tempNode = rolloutNode;
    auto &preferred = rolloutPreferred;
    tempNode.edges.clear();
    preferred.clear();
    while (!isTerminalState(state)) {
        ++simulationIdx;
        enumerateActionsImpl(tempNode, state, preservePotions);
        if (tempNode.edges.empty()) {
            std::cerr << state.seed << " " << simulationIdx << std::endl;
            std::cerr << state.monsters.arr[0].getName() << " " << state.floorNum << " " << monsterEncounterStrings[static_cast<int>(state.encounter)] << std::endl;
            assert(false);
        }

        auto dist = std::uniform_int_distribution<int>(0, static_cast<int>(tempNode.edges.size())-1);
        // Tree expansion still includes every legal action. Only the rollout
        // policy gives END_TURN one tenth the weight while cards are playable.
        const bool hasCard = std::any_of(tempNode.edges.begin(), tempNode.edges.end(),
            [](const auto &edge) { return edge.action.getActionType() == ActionType::CARD; });
        int selectedIdx;
        std::uniform_int_distribution<int> keepEndTurn(0, 9);
        do {
            selectedIdx = dist(randGen);
        } while (hasCard && tempNode.edges[selectedIdx].action.getActionType() == ActionType::END_TURN
                 && keepEndTurn(randGen) != 0);

        // Preserve the accepted sampler's CARD/POTION/END_TURN choice.
        // On half of CARD draws (three quarters for combat4), prefer expert ordering;
        // sample uniformly among tied cards/targets. Tree expansion is unchanged.
        if (tempNode.edges[selectedIdx].action.getActionType() == ActionType::CARD
                && (combat4Enabled ? std::uniform_int_distribution<int>(0, 3)(randGen) != 0
                                   : std::uniform_int_distribution<int>(0, 1)(randGen) == 1)) {
            int bestOrder = std::numeric_limits<int>::max();
            preferred.clear();
            for (int i = 0; i < static_cast<int>(tempNode.edges.size()); ++i) {
                const auto &candidate = tempNode.edges[i].action;
                if (candidate.getActionType() != ActionType::CARD) continue;
                const int order = search::Expert::getPlayOrdering(
                    state.cards.hand[candidate.getSourceIdx()].getId());
                if (order < bestOrder) {
                    bestOrder = order;
                    preferred.clear();
                }
                if (order == bestOrder) preferred.push_back(i);
            }
            selectedIdx = preferred[std::uniform_int_distribution<int>(
                0, static_cast<int>(preferred.size()) - 1)(randGen)];
        }

        if (focusTargets) {
            const auto chosen = tempNode.edges[selectedIdx].action;
            if (chosen.getActionType() == ActionType::CARD) {
                const auto &card = state.cards.hand[chosen.getSourceIdx()];
                if (card.getType() == CardType::ATTACK && card.requiresTarget()) {
                    int bestDurability = state.monsters.arr[chosen.getTargetIdx()].curHp
                                       + state.monsters.arr[chosen.getTargetIdx()].block;
                    // Change only the target of this sampled attack. All options
                    // come from the legal-action list; ties keep the sampled target.
                    for (int i = 0; i < static_cast<int>(tempNode.edges.size()); ++i) {
                        const auto a = tempNode.edges[i].action;
                        if (a.getActionType() != ActionType::CARD ||
                            a.getSourceIdx() != chosen.getSourceIdx()) continue;
                        const auto &m = state.monsters.arr[a.getTargetIdx()];
                        const int durability = m.curHp + m.block;
                        if (durability < bestDurability) {
                            bestDurability = durability;
                            selectedIdx = i;
                        }
                    }
                }
            }
        }
        const auto action = tempNode.edges[selectedIdx].action;
//        action.printDesc(std::cout, state) << std::endl;
        actionStack.push_back(action);
        action.execute(state);

        tempNode.edges.clear();
    }
}

namespace sts::search {
template<class NodeLike>
void enumerateActionsImpl(NodeLike &node,
                                                               const BattleContext &bc, bool preservePotions) {
    switch (bc.inputState) {
        case InputState::PLAYER_NORMAL:
            enumerateCardActionsImpl(node, bc);
            enumeratePotionActionsImpl(node, bc, preservePotions);
            node.edges.push_back({Action(ActionType::END_TURN)});
            break;

        case InputState::CARD_SELECT:
            enumerateCardSelectActionsImpl(node, bc);
            break;

        default:
#ifdef sts_asserts
            std::cerr << "enumerateActionsForNode: invalid input state: " << static_cast<int>(bc.inputState) << std::endl;
            assert(false);
#endif
            break;
    }

#ifdef sts_print_debug
    std::cout << "{ (" << node.edges.size() << ") ";
    for (int i = 0; i < node.edges.size(); ++i) {
        node.edges[i].action.printDesc(std::cout, bc) << ", ";
    }
    std::cout << " }" << std::endl;
#endif
}

template<class NodeLike>
void enumerateCardActionsImpl(NodeLike &node,
                                                            const BattleContext &bc) {
    if (!bc.isCardPlayAllowed()) {
        return;
    }

    fixed_list<std::pair<int,int>, 10> playableHandIdxs;
    for (int handIdx = 0; handIdx < bc.cards.cardsInHand; ++handIdx) {
        const auto &c = bc.cards.hand[handIdx];
        if (!c.canUseOnAnyTarget(bc)) {
            continue;
        }

        bool isUniqueAction = true;

        if (handIdx > 0) {
            const auto &lastCard = bc.cards.hand[handIdx-1];

            bool isEqualToLastCard = c.id == lastCard.id &&
                    c.getUpgradeCount() == lastCard.getUpgradeCount() &&
                    // both should be less than deck size c.uniqueId < bc.cards.deck
                    c.costForTurn == lastCard.costForTurn &&
                    c.cost == lastCard.cost &&
                    c.freeToPlayOnce == lastCard.freeToPlayOnce &&
                    c.specialData == lastCard.specialData;

            if (isEqualToLastCard) {
                isUniqueAction = false;
            }
        }

        if (isUniqueAction) {
            playableHandIdxs.push_back( {handIdx, search::Expert::getPlayOrdering(c.getId())} );
        }
    }

    std::sort(playableHandIdxs.begin(), playableHandIdxs.end(), [](auto a, auto b) { return a.second < b.second; });

    for (auto pair : playableHandIdxs) {
        const auto handIdx = pair.first;
        const auto &c = bc.cards.hand[handIdx];

        if (c.requiresTarget()) {
            for (int tIdx = bc.monsters.monsterCount-1; tIdx >= 0; --tIdx) {
                if (!bc.monsters.arr[tIdx].isTargetable()) {
                    continue;
                }
                node.edges.push_back({Action(ActionType::CARD, handIdx, tIdx)});
            }
        } else {
            node.edges.push_back({Action(ActionType::CARD, handIdx)});
        }
    }

}

template<class NodeLike>
void enumeratePotionActionsImpl(NodeLike &node, const BattleContext &bc, bool preservePotions) {
    for (int i = 0; i < bc.potionCapacity; ++i) {
        const auto p = bc.potions[i];
        if (p == Potion::EMPTY_POTION_SLOT || p == Potion::INVALID) continue;
        if (potionRequiresTarget(p)) {
            for (int t = 0; t < bc.monsters.monsterCount; ++t) {
                Action use(ActionType::POTION, i, t);
                if (use.isValidAction(bc)) node.edges.push_back({use});
            }
        } else {
            Action use(ActionType::POTION, i);
            if (use.isValidAction(bc)) node.edges.push_back({use});
        }
        Action discard(ActionType::POTION, i, -1);
        // No reliable in-combat replacement proof: omit all discard edges.
        if (!preservePotions && discard.isValidAction(bc)) node.edges.push_back({discard});
    }
}

template <typename NodeLike, typename ForwardIt>
void setupCardOptionsHelper(NodeLike &node, const ForwardIt begin, const ForwardIt end, const std::function<bool(const CardInstance &)> &p= nullptr) {
    for (int i = 0; begin+i != end; ++i) {
        const auto &c = begin[i];
        if (!p || (p(c))) {
            node.edges.push_back(
                    {search::Action(search::ActionType::SINGLE_CARD_SELECT, i)}
                );
        }
    }
}

template<class NodeLike>
void enumerateCardSelectActionsImpl(NodeLike &node,
                                                                  const BattleContext &bc) {

    switch (bc.cardSelectInfo.cardSelectTask) {
        case CardSelectTask::ARMAMENTS:
            setupCardOptionsHelper( node, bc.cards.hand.begin(), bc.cards.hand.begin() + bc.cards.cardsInHand,
                                    [] (const CardInstance &c) { return c.canUpgrade(); });
            break;

        case CardSelectTask::CODEX:
            for (int i = 0; i < 4; ++i) { // i -> 3 action means skip
                node.edges.push_back({Action(search::ActionType::SINGLE_CARD_SELECT, i)});
            }
            break;

        case CardSelectTask::DISCOVERY:
            for (int i = 0; i < 3; ++i) {
                node.edges.push_back({Action(search::ActionType::SINGLE_CARD_SELECT, i)});
            }
            break;

        case CardSelectTask::DUAL_WIELD:
            setupCardOptionsHelper( node, bc.cards.hand.begin(), bc.cards.hand.begin() + bc.cards.cardsInHand,
                                    [] (const CardInstance &c) {
                                        return c.getType() == CardType::POWER || c.getType() == CardType::ATTACK;
                                    });
            break;

        case CardSelectTask::EXHUME:
            setupCardOptionsHelper(node, bc.cards.exhaustPile.begin(), bc.cards.exhaustPile.end(),
                                   [](const auto &c) { return c.getId() != CardId::EXHUME; });
            break;

        case CardSelectTask::EXHAUST_ONE:
            setupCardOptionsHelper(node, bc.cards.hand.begin(), bc.cards.hand.begin() + bc.cards.cardsInHand);
            break;

        case CardSelectTask::FORETHOUGHT:
        case CardSelectTask::LIQUID_MEMORIES_POTION:
            for (const auto &action : Action::enumerateCardSelectActions(bc)) node.edges.push_back({action});
            break;

        case CardSelectTask::WARCRY:
            setupCardOptionsHelper(node, bc.cards.hand.begin(), bc.cards.hand.begin() + bc.cards.cardsInHand);
            break;

        case CardSelectTask::HEADBUTT:
            setupCardOptionsHelper(node, bc.cards.discardPile.begin(), bc.cards.discardPile.end());
            break;

        case CardSelectTask::SECRET_TECHNIQUE:
            setupCardOptionsHelper(node, bc.cards.drawPile.begin(), bc.cards.drawPile.end(),
                                    [] (const CardInstance &c) {
                                        return c.getType() == CardType::SKILL;
                                    });
            break;

        case CardSelectTask::SECRET_WEAPON:
            setupCardOptionsHelper(node, bc.cards.drawPile.begin(), bc.cards.drawPile.end(),
                                    [] (const CardInstance &c) {
                                        return c.getType() == CardType::ATTACK;
                                    });
            break;

        case CardSelectTask::EXHAUST_MANY:
        case CardSelectTask::GAMBLE:
            for (const auto &action : Action::enumerateCardSelectActions(bc)) {
                node.edges.push_back({action});
            }
            break;

        default:
#ifdef sts_asserts
            assert(false);
#endif
            break;
    }
}

} // namespace sts::search

void search::BattleScumSearcher2::enumerateActionsForNode(Node &node, const BattleContext &bc) {
    expansionActions.edges.clear();
    enumerateActionsImpl(expansionActions, bc, preservePotions);
    appendActions(node, expansionActions.edges);
}
void search::BattleScumSearcher2::enumerateCardActions(Node &node, const BattleContext &bc) {
    expansionActions.edges.clear();
    enumerateCardActionsImpl(expansionActions, bc);
    appendActions(node, expansionActions.edges);
}
void search::BattleScumSearcher2::enumeratePotionActions(Node &node, const BattleContext &bc) {
    expansionActions.edges.clear();
    enumeratePotionActionsImpl(expansionActions, bc, preservePotions);
    appendActions(node, expansionActions.edges);
}
void search::BattleScumSearcher2::enumerateCardSelectActions(Node &node, const BattleContext &bc) {
    expansionActions.edges.clear();
    enumerateCardSelectActionsImpl(expansionActions, bc);
    appendActions(node, expansionActions.edges);
}

double getNonMinionMonsterCurHpRatio(const BattleContext &bc) {
    int curHpTotal = 0;
    int maxHpTotal = 0;

    for (int i = 0; i < bc.monsters.monsterCount; ++i) {
        const auto &m = bc.monsters.arr[i];
        if (!m.hasStatus<MS::MINION>() && m.id != sts::MonsterId::INVALID) {
            curHpTotal += m.curHp;
            maxHpTotal += m.maxHp;
        }
    }

    if (curHpTotal == 0 || maxHpTotal == 0) {
        return 0;
    }

    return (double)curHpTotal / maxHpTotal;
}

static double evaluatePotionEndState(const BattleContext &bc, double potionScore) {
    if (bc.outcome == Outcome::UNDECIDED) return -1000000.0;

    if (bc.outcome == Outcome::PLAYER_VICTORY) {
        return 100 * (35 + bc.player.curHp + potionScore - (bc.turn * 0.01));
    } else if (bc.outcome == Outcome::PLAYER_ESCAPE) {
        return 100 * (bc.player.curHp + potionScore);
    } else {
//        double statusScore =
//                (bc.player.getStatus<PS::STRENGTH>() * .5);
        const bool couldHaveSpikers = bc.encounter == MonsterEncounter::THREE_SHAPES || bc.encounter == MonsterEncounter::FOUR_SHAPES;
        double energyPenalty = bc.energyWasted * -0.2 * (couldHaveSpikers ? 0 : 1);
        double drawBonus = bc.cardsDrawn * 0.03;
        double aliveScore = bc.monsters.monstersAlive*-1;

        return (1-getNonMinionMonsterCurHpRatio(bc))*10 + aliveScore + energyPenalty + std::min(20.0, drawBonus + bc.turn * .2) + potionScore / 2;
    }
}

double search::BattleScumSearcher2::evaluateEndState(const BattleContext &bc) {
    return evaluatePotionEndState(bc, bc.potionCount * 4);
}

// No inventory value for a failed terminal, including an undecided cutoff.
double search::BattleScumSearcher2::evaluateEndState4q(const BattleContext &bc) {
    const bool survived = bc.outcome == Outcome::PLAYER_VICTORY || bc.outcome == Outcome::PLAYER_ESCAPE;
    return evaluatePotionEndState(bc, survived ? bc.potionCount * 4 : 0);
}

double search::BattleScumSearcher2::evaluateEndState4r(const BattleContext &bc, int initialMaxHp) {
    if (bc.outcome != Outcome::PLAYER_VICTORY) return evaluateEndState4q(bc);
    const auto hp = bc.victoryHpRelics.project(bc.player.curHp, bc.player.maxHp);
    // Replace only the HP term; keep the existing Feed, potion and turn values.
    // The projection cannot create rewards, enter another room or consume RNG.
    return evaluateEndState4q(bc) + 100.0 * (hp.curHp - bc.player.curHp)
        + 100.0 * std::max(0, bc.player.maxHp - initialMaxHp);
}

struct LayerStruct {
    const search::BattleScumSearcher2::Node *node;
    BattleContext *bc;
    int edgeIdx;
};

typedef std::pair<search::BattleScumSearcher2::Edge, std::unique_ptr<const BattleContext>> EdgeInfo;

std::vector<EdgeInfo> getEdgesForLayer(const search::BattleScumSearcher2 &s, int layerNum) {
    if (layerNum <= 0) {
        return {};
    }

    std::vector<EdgeInfo> layerEdges;

    std::vector<LayerStruct> curStack { {&s.root, new BattleContext(*s.rootState), 0} };

    while (!curStack.empty()) {
        if (curStack.size() == layerNum) {
            for (const auto &edge : curStack.back().node->edges) {
                layerEdges.emplace_back(edge, new BattleContext(*curStack.back().bc));
            }
        }

       // curStack size less than layerNum
       const bool visitedAll = curStack.back().edgeIdx >= curStack.back().node->edges.size();
       if (visitedAll || curStack.size() == layerNum) {
           delete curStack.back().bc;
           curStack.pop_back();
           continue;
       }

        // visit next edge
        auto &nextIdx = curStack.back().edgeIdx;
        const auto action = curStack.back().node->edges[nextIdx].action;

        BattleContext bc(*curStack.back().bc);
        action.execute(bc);

        curStack.push_back( {&curStack.back().node->edges[nextIdx++].node, new BattleContext(bc), 0} );
    }

    return layerEdges;
}

void search::BattleScumSearcher2::printSearchTree(std::ostream &os, int levels) {
    std::vector<std::vector<EdgeInfo>> layerEdges;
    for (int depth = 1; depth <= levels; ++depth) {
        layerEdges.push_back(getEdgesForLayer(*this, depth));
    }

//    auto maxIt = std::max(layerEdges.begin(), layerEdges.end(), [](auto a, auto b) { return a->size() < b->size(); });
//    if (maxIt == layerEdges.end()) {
//        return;
//    }
//    // maxIt points to something
//    const auto maxSize = maxIt->size();
//    constexpr auto edgeWidth = 30;

    for (int depth = 0; depth < levels; ++depth) {
        for (const auto &x : layerEdges[depth]) {
            os << "(" << x.first.node.simulationCount << ")";
            x.first.action.printDesc(os, *x.second) << "\t";
        }
        std::cout << '\n';
    }

}

void search::BattleScumSearcher2::printSearchStack(std::ostream &os, bool skipLast) {
    for (int i = 0; i < actionStack.size(); ++i) {
        const auto &a = actionStack[i];
        os << std::hex << a.bits << '\n';
    }

    os.flush();

//    BattleContext curBc = *rootState;
//    os << "explorationParameter: " << explorationParameter << '\n';
//    os << "bestActionValue: " << bestActionValue << '\n';
//    os << "minActionValue: " << minActionValue << '\n';
//    os << "outcomePlayerHp: " << outcomePlayerHp << '\n';
//    os << "root node:\n";
//    os << curBc << "\n";
//
//    for (int i = 0; i < actionStack.size(); ++i) {
//        if (i < searchStack.size()) {
//            const auto &n = searchStack[i];
//            os << i << " nodeSearched: " << n->simulationCount << " { ";
//            for (const auto &edge : n->edges) {
//                os << "(" << edge.node.simulationCount << ")";
//                edge.action.printDesc(os, curBc) << " ";
//            }
//            os << "}\n";
//        }
//
//        const auto &a = actionStack[i];
//        os << i << " actionTaken: ";
//        a.printDesc(os, curBc) << '\n';
//
//        if (skipLast && (i + 1 >= actionStack.size())) {
//            break;
//        }
//
//        a.execute(curBc);
//        os << curBc << '\n';
//    }
//
//    os.flush();
}
