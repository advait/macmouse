// Compare the portable model with outputs recorded from the installed macOS
// 26.5 (25F71) ARM64e accelerator at every tracking-speed tick: every row must
// match bit for bit. Files are named speed-NN.csv.gz for slider tick NN.
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
static_assert(std::size(kSpeeds) == 10, "the slider has ten ticks");
uint64_t bits(double v) { uint64_t b; std::memcpy(&b, &v, sizeof b); return b; }
} // namespace

int main(int argc, char** argv) {
    if (argc < 2) return std::fprintf(stderr, "usage: %s speed-NN.csv.gz...\n", argv[0]), 2;
    unsigned long total = 0, failed = 0;
    for (int i = 1; i < argc; ++i) {
        const char* name = std::strstr(argv[i], "speed-");
        const int   tick = name ? std::atoi(name + 6) : 0;
        if (tick < 1 || tick > 10 || kSpeeds[tick - 1].tick != tick) return std::fprintf(stderr, "%s: no tick in name\n", argv[i]), 2;
        const auto& speed = kSpeeds[tick - 1];
        const mouse_parity::PointerProfile profile{
            std::vector<mouse_parity::Segment>(std::begin(kSegments) + speed.first, std::begin(kSegments) + speed.first + speed.count)};
        const std::string cmd = std::string("gzip -dc '") + argv[i] + "'";
        FILE* in = popen(cmd.c_str(), "r");
        if (!in) return std::perror("gzip"), 2;
        char line[512];
        if (!std::fgets(line, sizeof line, in) || std::strncmp(line, "timestamp_ns,dx,dy,out_dx,out_dy", 32))
            return std::fprintf(stderr, "%s: bad header\n", argv[i]), 2;
        unsigned long rows = 0, mismatches = 0;
        while (std::fgets(line, sizeof line, in)) {
            char* p = std::strchr(line, ',') + 1; // timestamp is irrelevant at rate 0
            const double dx = std::strtod(p, &p), dy = std::strtod(p + 1, &p);
            const double ex = std::strtod(p + 1, &p), ey = std::strtod(p + 1, &p);
            const auto out = profile.apply(dx, dy);
            if (bits(out[0]) != bits(ex) || bits(out[1]) != bits(ey)) {
                if (++mismatches <= 5) std::fprintf(stderr, "tick %d mismatch (%a,%a): %a,%a != %a,%a\n", tick, dx, dy, out[0], out[1], ex, ey);
            }
            ++rows;
        }
        pclose(in);
        std::printf("tick %2d (scaling %g): %lu rows, %lu mismatches\n", tick, speed.scaling, rows, mismatches);
        total += rows;
        failed += mismatches + (rows == 0);
    }
    std::printf("%lu rows, %lu mismatches\n", total, failed);
    return total > 0 && failed == 0 ? 0 : 1;
}
