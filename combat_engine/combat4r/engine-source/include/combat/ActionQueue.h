#ifndef STS_LIGHTSPEED_ACTIONQUEUE_H
#define STS_LIGHTSPEED_ACTIONQUEUE_H

#include "sts_common.h"
#include <array>
#include <bitset>
#include <cassert>
#include <functional>
#include <limits>
#include <stdexcept>
#include <vector>
#include <type_traits>
#include <utility>

namespace sts {

    class BattleContext;
    using ActionFunction = std::function<void(BattleContext &)>;

    struct Action {
        ActionFunction actFunc;
        bool clearOnCombatVictory = true;
        Action() = default;
        template<class F, std::enable_if_t<std::is_constructible_v<ActionFunction, F &&>, int> = 0>
        Action(F &&function, bool clear = true)
            : actFunc(std::forward<F>(function)), clearOnCombatVictory(clear) {}
    };

    // Keep ordinary queues inline, but do not impose a game-rule limit on
    // deferred actions (for example, a late Book of Stabbing multi-attack).
    template<int inlineCapacity>
    struct ActionQueue {
        static_assert(inlineCapacity > 0);
        int front = 0;
        int back = 0;
        int size = 0;

        ActionQueue() = default;
        ActionQueue(const ActionQueue &other)
            : front(other.front), back(other.back), size(other.size),
              clearFlags(other.clearFlags), expanded(other.expanded.size()) {
            copyPending(other);
        }
        ActionQueue &operator=(const ActionQueue &other) {
            if (this == &other) return *this;
            for (auto &function : actions) function = nullptr;
            expanded.clear();
            expanded.resize(other.expanded.size());
            front = other.front;
            back = other.back;
            size = other.size;
            clearFlags = other.clearFlags;
            copyPending(other);
            return *this;
        }
        ActionQueue(ActionQueue &&) = default;
        ActionQueue &operator=(ActionQueue &&) = default;

        void clear() {
            size = front = back = 0;
        }

        void pushFront(const Action &action) {
            ensureRoom();
            if (--front < 0) front = getCapacity() - 1;
            store(front, action);
            ++size;
        }

        void pushFront(Action &&action) {
            ensureRoom();
            if (--front < 0) front = getCapacity() - 1;
            store(front, std::move(action));
            ++size;
        }

        void pushBack(const Action &action) {
            ensureRoom();
            if (back == getCapacity()) back = 0;
            store(back, action);
            ++back;
            ++size;
        }

        void pushBack(Action &&action) {
            ensureRoom();
            if (back == getCapacity()) back = 0;
            store(back, std::move(action));
            ++back;
            ++size;
        }

        [[nodiscard]] bool isEmpty() const { return size == 0; }

        ActionFunction popFront() {
            assert(size > 0);
            // Return a separate callable: it may mutate or grow this queue.
            ActionFunction action = std::move(functionAt(front));
            if (++front == getCapacity()) front = 0;
            --size;
            return action;
        }

        [[nodiscard]] int getCapacity() const {
            return expanded.empty() ? inlineCapacity : static_cast<int>(expanded.size());
        }

        void clearCombatActions() {
            const int oldSize = size;
            int read = front, write = front, retained = 0;
            for (int i = 0; i < oldSize; ++i) {
                if (!clearAt(read)) {
                    if (write != read) store(write, Action(std::move(functionAt(read)), false));
                    if (++write == getCapacity()) write = 0;
                    ++retained;
                }
                if (++read == getCapacity()) read = 0;
            }
            size = retained;
            // A later append must follow the compacted survivors, including
            // when the circular queue crossed its storage boundary.
            back = write;
        }

    private:
        std::array<ActionFunction, inlineCapacity> actions;
        std::bitset<inlineCapacity> clearFlags;
        std::vector<Action> expanded;

        void copyPending(const ActionQueue &other) {
            int index = front;
            for (int i = 0; i < size; ++i) {
                if (expanded.empty()) actions[index] = other.actions[index];
                else expanded[index] = other.expanded[index];
                if (++index == getCapacity()) index = 0;
            }
        }

        ActionFunction &functionAt(int index) {
            return expanded.empty() ? actions[index] : expanded[index].actFunc;
        }

        [[nodiscard]] bool clearAt(int index) const {
            return expanded.empty() ? clearFlags[index] : expanded[index].clearOnCombatVictory;
        }

        void store(int index, const Action &action) {
            if (expanded.empty()) {
                actions[index] = action.actFunc;
                clearFlags.set(index, action.clearOnCombatVictory);
            } else {
                expanded[index] = action;
            }
        }

        void store(int index, Action &&action) {
            if (expanded.empty()) {
                actions[index] = std::move(action.actFunc);
                clearFlags.set(index, action.clearOnCombatVictory);
            } else {
                expanded[index] = std::move(action);
            }
        }

        void ensureRoom() {
            const int oldCapacity = getCapacity();
            if (size < oldCapacity) return;
            if (oldCapacity > std::numeric_limits<int>::max() / 2)
                throw std::length_error("action queue storage exhausted");
            std::vector<Action> grown(static_cast<std::size_t>(oldCapacity) * 2);
            int source = front;
            for (int i = 0; i < size; ++i) {
                grown[i] = Action(std::move(functionAt(source)), clearAt(source));
                if (++source == oldCapacity) source = 0;
            }
            expanded = std::move(grown);
            front = 0;
            back = size;
        }
    };
}
#endif
