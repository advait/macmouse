#pragma once
#include <array>
#include <cmath>
#include <vector>
#include <stdexcept>
// Independent model of macOS 26.5 (25F71) IOHIDTableAcceleration as used for
// mouse pointer motion (rate 0, fixed multiplier 1). Bit-exact against the
// installed ARM64e accelerator: see tests/apple-pointer-vectors.csv.gz.
namespace mouse_parity {
struct Segment { double m, b, x; };
class PointerProfile {
 std::vector<Segment> segments;
public:
 explicit PointerProfile(std::vector<Segment> s):segments(std::move(s)) {
  if(segments.empty())throw std::invalid_argument("empty acceleration table");
 }
 std::array<double,2> apply(double dx,double dy)const {
  // Keep mul+add separate: Apple's magnitude calculation does not use FMA.
  double magnitude=std::floor(std::sqrt(dx*dx+dy*dy));
  double v=magnitude<0x1p-16?0x1p-16:magnitude;
  const Segment* chosen=&segments.back();
  for(const auto&s:segments)if(!(v>s.x)){chosen=&s;break;}
  // The shipped ARM64e table multiplier uses FMADD. Explicit fma is required.
  double gain=std::fma(chosen->m,v,chosen->b)/v;
  return {dx*gain,dy*gain};
 }
};
}
