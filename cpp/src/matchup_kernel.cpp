#include "fantasy_optimizer/matchup.hpp"

#include <algorithm>
#include <array>
#include <stdexcept>

namespace fantasy_optimizer {
void matchup_outcomes(std::span<const std::int64_t> games,
                      std::span<const std::int64_t> teams,
                      std::span<const std::int64_t> observed,
                      std::span<std::int8_t> output, bool zero_tie) {
    const auto scenarios = output.size() / 9;
    if (output.size() % 9 != 0 || observed.size() != 22 ||
        games.size() != scenarios * teams.size() * 11) {
        throw std::invalid_argument("Invalid kernel shapes");
    }
    for (const auto team : teams) {
        if (team < 0 || team > 1) {
            throw std::invalid_argument("Invalid team index");
        }
    }
    for (const auto array : {games, observed}) {
        for (const auto value : array) {
            if (value < 0 || value > 10000000) {
                throw std::invalid_argument("Invalid count bound");
            }
        }
    }
    constexpr std::array<std::size_t, 9> stats{0, 2, 4, 5, 6, 7, 8, 9, 10};
    for (std::size_t scenario = 0; scenario < scenarios; ++scenario) {
        std::array<std::array<std::int64_t, 11>, 2> totals{};
        std::copy_n(observed.data(), 11, totals[0].begin());
        std::copy_n(observed.data() + 11, 11, totals[1].begin());
        for (std::size_t game = 0; game < teams.size(); ++game) {
            auto &team = totals[static_cast<std::size_t>(teams.data()[game])];
            for (std::size_t stat = 0; stat < 11; ++stat) {
                const auto value =
                    games.data()[(scenario * teams.size() + game) * 11 + stat];
                if (team[stat] > 10000000 - value) {
                    throw std::invalid_argument("Aggregate count exceeds bound");
                }
                team[stat] += value;
            }
        }
        for (std::size_t category = 0; category < stats.size(); ++category) {
            const auto stat = stats[category];
            auto a = totals[0][stat];
            auto b = totals[1][stat];
            if (category < 2) {
                const auto da = totals[0][stat + 1];
                const auto db = totals[1][stat + 1];
                if (zero_tie && (da == 0 || db == 0)) {
                    a = 0;
                    b = 0;
                } else {
                    a *= std::max<std::int64_t>(db, 1);
                    b *= std::max<std::int64_t>(da, 1);
                }
            }
            const auto comparison = (a > b) - (a < b);
            output[scenario * 9 + category] =
                static_cast<std::int8_t>(category == 8 ? -comparison : comparison);
        }
    }
}
} // namespace fantasy_optimizer
