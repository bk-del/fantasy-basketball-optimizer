#pragma once

#include <cstdint>
#include <span>

namespace fantasy_optimizer {
void matchup_outcomes(std::span<const std::int64_t> games,
                      std::span<const std::int64_t> teams,
                      std::span<const std::int64_t> observed,
                      std::span<std::int8_t> output, bool zero_tie);
}
