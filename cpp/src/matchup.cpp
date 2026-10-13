#include "fantasy_optimizer/matchup.hpp"
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <memory>
#include <stdexcept>

namespace nb = nanobind;
using Counts = nb::ndarray<const std::int64_t, nb::c_contig, nb::device::cpu>;

namespace {
nb::ndarray<nb::numpy, std::int8_t> outcomes(const Counts &games, const Counts &teams,
                                             const Counts &observed, bool zero_tie) {
    if (games.ndim() != 3 || games.shape(2) != 11 || teams.ndim() != 1 ||
        teams.shape(0) != games.shape(1) || observed.ndim() != 2 ||
        observed.shape(0) != 2 || observed.shape(1) != 11 || games.shape(0) == 0) {
        throw std::invalid_argument("Invalid batch shapes");
    }
    auto output = std::make_unique<std::int8_t[]>(games.shape(0) * 9);
    fantasy_optimizer::matchup_outcomes({games.data(), games.size()},
                                        {teams.data(), teams.size()},
                                        {observed.data(), observed.size()},
                                        {output.get(), games.shape(0) * 9}, zero_tie);
    auto *data = output.release();
    nb::capsule owner(data, [](void *pointer) noexcept {
        delete[] static_cast<std::int8_t *>(pointer);
    });
    return {data, {games.shape(0), 9}, owner};
}
} // namespace

NB_MODULE(_matchup, module) {
    module.def("outcomes", &outcomes, nb::arg("games").noconvert(),
               nb::arg("teams").noconvert(), nb::arg("observed").noconvert(),
               nb::arg("zero_tie"));
}
