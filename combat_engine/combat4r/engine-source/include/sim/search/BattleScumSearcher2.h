//
// Created by keega on 9/17/2021.
//

#ifndef STS_LIGHTSPEED_BATTLESCUMSEARCHER2_H
#define STS_LIGHTSPEED_BATTLESCUMSEARCHER2_H

#include "sim/search/Action.h"

#include <functional>
#include <memory>
#include <random>
#include <iostream>
#include <limits>
#include <cstdint>
#include <vector>

#define STS_SEARCH_BLOCK_ARENA 1

namespace sts::search {

    struct RolloutNode {
        struct Edge { Action action; };
        std::vector<Edge> edges;
    };

    typedef std::function<double (const BattleContext&)> EvalFnc;

    // to find a solution to a battle with tree pruning
    struct BattleScumSearcher2 {
        class Edge;
        // Non-owning children. The searcher's arena owns every backing block;
        // growing the arena never relocates an existing node or child range.
        struct EdgeRange {
            Edge *data = nullptr;
            std::uint32_t count = 0;
            std::size_t size() const { return count; }
            bool empty() const { return count == 0; }
            Edge *begin();
            const Edge *begin() const;
            Edge *end();
            const Edge *end() const;
            Edge &operator[](std::size_t index);
            const Edge &operator[](std::size_t index) const;
            void clear() { data = nullptr; count = 0; }
        };
        struct Node {
            std::int64_t simulationCount = 0;
            double evaluationSum = 0;
            EdgeRange edges;
            // -2 means unknown; -1 is the bounded nonterminal rollout result.
            // A known terminal leaf stores its exact score in evaluationSum.
            int terminalHp = -2;
        };

        struct Edge {
            Action action;
            Node node;
        };

        class EdgeArena {
            struct Block {
                std::unique_ptr<Edge[]> data;
                std::size_t capacity;
                std::size_t used = 0;
            };
            std::vector<Block> blocks;
        public:
            Edge *allocate(std::size_t count);
            std::size_t storageBytes() const;
            std::size_t blockCount() const { return blocks.size(); }
        };
        // Nodes and EdgeRange copies are views into this search, not owners.
        // Use retainSubtree() to transfer a branch and reclaim its ancestors.
        EdgeArena edgeArena;
        RolloutNode expansionActions;

        std::unique_ptr<const BattleContext> rootState;
        Node root;

        EvalFnc evalFnc;
        double explorationParameter = 3*sqrt(2);
        bool focusTargets = false;
        // Per-search policy. Legacy callers retain every legal discard.
        bool preservePotions = false;
        bool combat4qEnabled = false; // death inventory has no continuation value
        bool combat4rEnabled = false;
        int combatInitialMaxHp = 0; // fixed across retained trees and replanning
        bool combat4Enabled = false; // opt-in rollout ordering; legacy defaults unchanged

        double bestActionValue = std::numeric_limits<double>::min();
        double minActionValue = std::numeric_limits<double>::max();
        int outcomePlayerHp = 0;

        std::vector<Action> bestActionSequence;
        std::default_random_engine randGen;

        std::vector<Node*> searchStack;
        std::vector<Action> actionStack;
        // Reused only by this searcher's sequential rollouts. No node or state
        // references escape; preserve enumeration and random-draw order.
        RolloutNode rolloutNode;
        std::vector<int> rolloutPreferred;
        // At most 32 complete first-action states within one search() call.
        // Includes rule state and RNG; no approximate state merging.
        std::vector<std::unique_ptr<const BattleContext>> prefixStates;
        bool prefixCaching = false;
        struct PrefixSnapshot {
            const Node *node = nullptr;
            std::unique_ptr<const BattleContext> state;
        };
        // Direct-mapped, tagged cache; collisions affect cost, never results.
        // Tree node addresses are stable during search(), then all tags expire.
        std::vector<PrefixSnapshot> deeperPrefixStates;

        explicit BattleScumSearcher2(const BattleContext &bc, EvalFnc evalFnc=&evaluateEndState);

        // public methods
        void search(int64_t simulations);
        void step();
        void appendActions(Node &node, const std::vector<RolloutNode::Edge> &actions);
        void retainSubtree(const Node &node);

        void updateFromEvaluation(const std::vector<Node *> &stack,
            const std::vector<Action> &actions, double evaluation, int terminalHp);

        // private helpers
        void updateFromPlayout(const std::vector<Node*> &stack, const std::vector<Action> &actionStack, const BattleContext &endState);
        [[nodiscard]] bool isTerminalState(const BattleContext &bc) const;

        double evaluateEdge(const Node &parent, int edgeIdx);
        int selectBestEdgeToSearch(const Node &cur);
        int selectFirstActionForLeafNode(const Node &leafNode);

        void playoutRandom(BattleContext &state, std::vector<Action> &actionStack);

        void enumerateActionsForNode(Node &node, const BattleContext &bc);
        void enumerateCardActions(Node &node, const BattleContext &bc);
        void enumeratePotionActions(Node &node, const BattleContext &bc);
        void enumerateCardSelectActions(Node &node, const BattleContext &bc);
        static double evaluateEndState(const BattleContext &bc);
        static double evaluateEndState4q(const BattleContext &bc);
        static double evaluateEndState4r(const BattleContext &bc, int initialMaxHp);

        void printSearchTree(std::ostream &os, int levels);
        void printSearchStack(std::ostream &os, bool skipLast=false);
    };

    extern thread_local BattleScumSearcher2 *g_debug_scum_search;

}


#endif //STS_LIGHTSPEED_BATTLESCUMSEARCHER2_H
