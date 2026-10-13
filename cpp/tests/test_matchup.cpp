#define CATCH_CONFIG_MAIN
#include <catch2/catch.hpp>

#include "fantasy_optimizer/matchup.hpp"

#include <array>
#include <stdexcept>

TEST_CASE("Weighted percentages, turnovers and observed partial totals") {
    const std::array<std::int64_t, 11> games{1, 1, 1, 1, 0, 3, 1, 1, 1, 1, 1};
    const std::array<std::int64_t, 1> teams{0};
    const std::array<std::int64_t, 22> observed{0, 9,  0, 9,  0, 0,  0, 0, 0, 0, 0,
                                                4, 10, 4, 10, 0, 12, 0, 0, 0, 0, 2};
    std::array<std::int8_t, 9> output{};
    fantasy_optimizer::matchup_outcomes(games, teams, observed, output, false);
    const std::array<std::int8_t, 9> expected{-1, -1, 0, -1, 1, 1, 1, 1, 1};
    REQUIRE(output == expected);
}

TEST_CASE("Empty remaining schedule ties all categories") {
    const std::array<std::int64_t, 22> zero{};
    std::array<std::int8_t, 9> output{};
    fantasy_optimizer::matchup_outcomes({}, {}, zero, output, false);
    const std::array<std::int8_t, 9> expected{};
    REQUIRE(output == expected);
}

TEST_CASE("Invalid teams and overflow are rejected") {
    const std::array<std::int64_t, 11> games{1, 1, 1, 1, 0, 3, 1, 1, 1, 1, 1};
    const std::array<std::int64_t, 1> invalid_team{2};
    const std::array<std::int64_t, 22> zero{};
    std::array<std::int8_t, 9> output{};
    REQUIRE_THROWS_AS(
        fantasy_optimizer::matchup_outcomes(games, invalid_team, zero, output, false),
        std::invalid_argument);
    const std::array<std::int64_t, 1> team{0};
    auto full = zero;
    full[0] = 10000000;
    REQUIRE_THROWS_AS(
        fantasy_optimizer::matchup_outcomes(games, team, full, output, false),
        std::invalid_argument);
}
