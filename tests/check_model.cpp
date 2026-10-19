// Compare the portable model with outputs recorded from the installed macOS
// 26.5 (25F71) ARM64e accelerator: every row must match bit for bit.
#include "pointer_profile.hpp"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <string>
#include <vector>

namespace {
#include "macmouse_table.inc"
uint64_t bits(double v) { uint64_t b; std::memcpy(&b, &v, sizeof b); return b; }
} // namespace

int main(int argc, char** argv) {
    if (argc != 2) return std::fprintf(stderr, "usage: %s vectors.csv.gz\n", argv[0]), 2;
    const std::string cmd = std::string("gzip -dc '") + argv[1] + "'";
    FILE* in = popen(cmd.c_str(), "r");
    if (!in) return std::perror("gzip"), 2;
    const mouse_parity::PointerProfile profile{std::vector<mouse_parity::Segment>(std::begin(kTable), std::end(kTable))};
    char line[512];
    if (!std::fgets(line, sizeof line, in) || std::strncmp(line, "timestamp_ns,dx,dy,out_dx,out_dy", 32))
        return std::fprintf(stderr, "bad header\n"), 2;
    unsigned long rows = 0, mismatches = 0;
    while (std::fgets(line, sizeof line, in)) {
        char* p = std::strchr(line, ',') + 1; // timestamp is irrelevant at rate 0
        const double dx = std::strtod(p, &p), dy = std::strtod(p + 1, &p);
        const double ex = std::strtod(p + 1, &p), ey = std::strtod(p + 1, &p);
        const auto out = profile.apply(dx, dy);
        if (bits(out[0]) != bits(ex) || bits(out[1]) != bits(ey)) {
            if (++mismatches <= 5) std::fprintf(stderr, "mismatch (%a,%a): %a,%a != %a,%a\n", dx, dy, out[0], out[1], ex, ey);
        }
        ++rows;
    }
    pclose(in);
    std::printf("%lu rows, %lu mismatches\n", rows, mismatches);
    return rows > 0 && mismatches == 0 ? 0 : 1;
}
