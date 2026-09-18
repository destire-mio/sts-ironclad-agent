#include <algorithm>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

// The queue contract needs only the callback's recipient. Native integration
// is checked separately by restoring the real overflowing battle.
namespace sts { class BattleContext { public: std::vector<int> observed; }; }
#include "combat/ActionQueue.h"

using Queue = sts::ActionQueue<8>;
using Model = std::deque<std::pair<int, bool>>;

static void require(bool value) {
    if (!value) throw std::runtime_error("observable callback order differs");
}

static void add(Queue &queue, Model &model, int value, bool front=false, bool clear=true) {
    sts::Action action([value](sts::BattleContext &context) { context.observed.push_back(value); }, clear);
    if (front) { queue.pushFront(action); model.push_front({value, clear}); }
    else { queue.pushBack(action); model.push_back({value, clear}); }
}

static void pop(Queue &queue, Model &model, sts::BattleContext &context) {
    require(!queue.isEmpty() && !model.empty());
    const int expected = model.front().first;
    model.pop_front();
    queue.popFront()(context);
    require(context.observed.back() == expected);
}

static void drain(Queue &queue, Model &model) {
    sts::BattleContext context;
    while (!model.empty()) pop(queue, model, context);
    require(queue.isEmpty());
}

static void victory(Queue &queue, Model &model) {
#ifdef OLD_QUEUE
    // Unchanged production caller from the source-control snapshot.
    int current = queue.front, place = queue.front;
    const int oldSize = queue.size;
    for (int i=0; i<oldSize; ++i) {
        if (current >= queue.getCapacity()) current = 0;
        if (queue.bits[current]) --queue.size;
        else {
            if (place >= queue.getCapacity()) place = 0;
            queue.arr[place] = queue.arr[current];
            queue.bits[place] = queue.bits[current];
            ++place;
        }
        ++current;
    }
#else
    queue.clearCombatActions();
#endif
    model.erase(std::remove_if(model.begin(), model.end(), [](auto value) { return value.second; }), model.end());
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const std::string test(argv[1]);
    try {
        Queue queue;
        Model model;
        sts::BattleContext context;
        if (test == "normal_wrap") {
            for (int i=0; i<1000; ++i) {
                add(queue, model, i, i%3 == 0);
                if (model.size() >= 6) pop(queue, model, context);
            }
        } else if (test == "growth_back" || test == "growth_front") {
            for (int i=0; i<512; ++i) add(queue, model, i, test == "growth_front");
        } else if (test == "growth_wrapped") {
            for (int i=0; i<6; ++i) add(queue, model, i);
            for (int i=0; i<4; ++i) pop(queue, model, context);
            for (int i=6; i<300; ++i) add(queue, model, i, i%5 == 0);
        } else if (test == "growth_copy") {
            for (int i=0; i<80; ++i) add(queue, model, i, i%3 == 0, i%2 == 0);
            Queue copy(queue);
            Model expected(model);
            add(queue, model, 1000, true);
            add(copy, expected, 2000);
            victory(copy, expected);
            drain(copy, expected);
        } else if (test == "victory_wrapped") {
            for (int i=0; i<6; ++i) add(queue, model, i, false, i == 5);
            for (int i=0; i<4; ++i) pop(queue, model, context);
            for (int i=6; i<10; ++i) add(queue, model, i, false, i == 6 || i == 9);
            victory(queue, model);
            add(queue, model, 10, false, false);
            add(queue, model, 11, true, false);
        } else if (test == "clear_reuse") {
            for (int i=0; i<100; ++i) add(queue, model, i);
            queue.clear(); model.clear();
            add(queue, model, 1000);
            add(queue, model, 1001, true);
        } else if (test == "executing_callback_grows_queue") {
            queue.pushBack(sts::Action([&queue](sts::BattleContext &recipient) {
                for (int i=0; i<512; ++i)
                    queue.pushBack(sts::Action([i](sts::BattleContext &next) { next.observed.push_back(i); }));
                recipient.observed.push_back(-1);
            }));
            queue.popFront()(context);
            require(context.observed == std::vector<int>{-1});
            for (int i=0; i<512; ++i) model.push_back({i, true});
        } else return 2;
        drain(queue, model);
        std::cout << test << ": PASS\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << test << ": " << error.what() << '\n';
        return 1;
    }
}
