#pragma once

#include <array>
#include <bitset>
#include <cstdint>
#include <stdexcept>
#include "constants/PlayerStatusEffects.h"

namespace sts {
// PlayerStatus has a uint8_t representation. Keep every representable key,
// including absent-versus-zero semantics, without allocating tree nodes.
class PlayerStatusAmounts {
    std::array<std::int16_t, 256> values{};
    std::bitset<256> present;
public:
    std::int16_t &operator[](PlayerStatus status) {
        const auto index = static_cast<std::uint8_t>(status);
        present.set(index);
        return values[index];
    }
    bool contains(PlayerStatus status) const {
        return present.test(static_cast<std::uint8_t>(status));
    }
    const std::int16_t &at(PlayerStatus status) const {
        if (!contains(status)) throw std::out_of_range("missing player status amount");
        return values[static_cast<std::uint8_t>(status)];
    }
    std::int16_t &at(PlayerStatus status) {
        if (!contains(status)) throw std::out_of_range("missing player status amount");
        return values[static_cast<std::uint8_t>(status)];
    }
};
}
