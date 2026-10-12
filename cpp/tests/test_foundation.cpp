#include "fantasy_optimizer/foundation.hpp"

#include <iostream>

int main() {
    if (fantasy_optimizer::foundation_status() != "planned") {
        std::cerr << "Unexpected foundation status\n";
        return 1;
    }
    return 0;
}
