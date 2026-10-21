// macmouse: Hyprland plugin applying the macOS 26.5 pointer transform to
// selected mice. See docs/ALGORITHM.md.
//
// Per libinput motion event from a selected device, using its unaccelerated
// integer counts d:
//   a = PointerProfile::apply(d)          bit-exact Apple table (rate0) for the
//                                         selected tracking-speed tick (1..10)
//   n = binary32(a)                       NX motion projection
//   n == 0  -> no cursor movement
//   else    -> next = trunc24.8(p + n)    WindowServer fixed-point feedback
// The motion hook arms a one-shot cursor step; the CPointerManager::move hook
// consumes it against the actual position at move time (after Hyprland's
// pre-move warp check), regardless of force_no_accel's stock vector choice, and
// moves by next - p, which binary64 addition maps exactly onto `next`.
// Relative-pointer clients receive n as the accelerated vector and the
// unchanged raw counts as unaccel; other devices are untouched.
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/pointer/PointerManager.hpp>
#include <hyprland/src/devices/IPointer.hpp>
#include "pointer_profile.hpp"
#include <cfenv>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <mutex>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace {
#include "macmouse_table.inc" // generated from profiles/tracking-speeds.hex.csv
static_assert(std::size(kSpeeds) == 10, "the slider has ten ticks");

using MotionFn = void (*)(CInputManager*, IPointer::SMotionEvent);
using MoveFn   = void (*)(Pointer::CPointerManager*, const Vector2D&);

struct TraceRow {
    uint64_t seq;
    uint32_t timeMs;
    double   rawX, rawY, stockX, stockY, tableX, tableY;
    float    nxX, nxY;
    double   beforeX, beforeY, appliedX, appliedY, afterX, afterY;
    int      kind; // 0 transformed, 1 no_motion, 2 refused, 3 other device, 4 selected but no cursor move
    std::string device;
};

HANDLE                       g_handle = nullptr;
CFunctionHook*               g_hook   = nullptr;
CFunctionHook*               g_moveHook = nullptr;
std::vector<mouse_parity::PointerProfile> makeProfiles() {
    std::vector<mouse_parity::PointerProfile> out;
    for (const auto& s : kSpeeds)
        out.emplace_back(std::vector<mouse_parity::Segment>(std::begin(kSegments) + s.first, std::begin(kSegments) + s.first + s.count));
    return out;
}
const std::vector<mouse_parity::PointerProfile> g_profiles = makeProfiles();
int                          g_speed    = 10; // slider tick; set by tools/load.sh from ~/.config/macmouse/tracking-speed
bool                         g_selftest = false;
bool                         g_enabled  = true;
bool                         g_quantize = true;
std::set<std::string>        g_devices; // set by tools/load.sh from ~/.config/macmouse/devices
uint64_t                     g_seq = 0, g_transformed = 0, g_noMotion = 0, g_refused = 0, g_other = 0, g_unmoved = 0;
size_t                       g_traceCap = 0;
std::vector<TraceRow>        g_trace;

uint64_t bits(double v) { uint64_t b; std::memcpy(&b, &v, sizeof b); return b; }
uint32_t bits(float v) { uint32_t b; std::memcpy(&b, &v, sizeof b); return b; }

// Expected outputs are the installed macOS 26.5 accelerator's results recorded
// in tests/apple-pointer-vectors.csv.gz, not values computed by this code.
bool selfTest() {
    struct V { int tick, x, y; double ex, ey; };
    const V vectors[] = {
        {1, 1, 0, 0.24000000000000002, 0.0}, {1, 4, 0, 0.9599999999999999, 0.0}, {1, -7, 3, -1.6799999999999997, 0.7199999999999999}, {1, 100, -37, 24.0, -8.879999999999999}, {1, -128, -128, -30.71999999999999, -30.71999999999999},
        {2, 1, 0, 0.20804395073653703, 0.0}, {2, 4, 0, 1.0344885168004525, 0.0}, {2, -7, 3, -2.0827350076658964, 0.8926007175710985}, {2, 100, -37, 40.96881529758423, -15.158461660106164}, {2, -128, -128, -45.72841031086512, -45.72841031086512},
        {3, 1, 0, 0.2217394004208783, 0.0}, {3, 4, 0, 1.4291498979471233, 0.0}, {3, -7, 3, -3.2909400306635876, 1.4104028702843947}, {3, 100, -37, 91.87526119033689, -33.99384664042465}, {3, -128, -128, -90.75364124346049, -90.75364124346049},
        {4, 1, 0, 0.22858712526304895, 0.0}, {4, 4, 0, 1.6264805885204587, 0.0}, {4, -7, 3, -3.895042542162432, 1.6693039466410422}, {4, 100, -37, 117.32848413671321, -43.41153913058389}, {4, -128, -128, -113.2662567097582, -113.2662567097582},
        {5, 1, 0, 0.23543485010521956, 0.0}, {5, 4, 0, 1.8238112790937941, 0.0}, {5, -7, 3, -4.4991450536612785, 1.928205022997691}, {5, 100, -37, 142.78170708308954, -52.82923162074313}, {5, -128, -128, -135.7788721760559, -135.7788721760559},
        {6, 1, 0, 0.20347880084175665, 0.0}, {6, 4, 0, 1.8982997958942436, 0.0}, {6, -7, 3, -4.901880061327171, 2.100805740568788}, {6, 100, -37, 159.75052238067377, -59.1076932808493}, {6, -128, -128, -150.787282486921, -150.787282486921},
        {7, 1, 0, 0.25434850105219575, 0.0}, {7, 4, 0, 2.3728747448678096, 0.0}, {7, -7, 3, -6.127350076658968, 2.626007175710986}, {7, 100, -37, 199.68815297584223, -73.88461660106162}, {7, -128, -128, -188.48410310865125, -188.48410310865125},
        {8, 1, 0, 0.30521820126263494, 0.0}, {8, 4, 0, 2.847449693841367, 0.0}, {8, -7, 3, -7.352820091990758, 3.151208610853182}, {8, 100, -37, 239.6257835710107, -88.66153992127396}, {8, -128, -128, -226.18092373038147, -226.18092373038147},
        {9, 1, 0, 0.3560879014730741, 0.0}, {9, 4, 0, 3.3220246428149296, 0.0}, {9, -7, 3, -8.578290107322552, 3.676410045995379}, {9, 100, -37, 279.5634141661791, -103.43846324148626}, {9, -128, -128, -263.87774435211173, -263.87774435211173},
        {10, 1, 0, 0.4069576016835133, 0.0}, {10, 4, 0, 3.796599591788487, 0.0}, {10, -7, 3, -9.803760122654342, 4.201611481137576}, {10, 100, -37, 319.50104476134754, -118.2153865616986}, {10, -128, -128, -301.574564973842, -301.574564973842},
    };
    if (std::fegetround() != FE_TONEAREST) return false;
    for (const auto& v : vectors) {
        auto a = g_profiles[v.tick - 1].apply(v.x, v.y);
        if (bits(a[0]) != bits(v.ex) || bits(a[1]) != bits(v.ey)) return false;
    }
    return true;
}

bool fixed24_8(double v, double& out) {
    const double s = v * 256.;
    if (!std::isfinite(s) || s < -2147483648. || s >= 2147483648.) return false;
    out = double(static_cast<int32_t>(s)) / 256.;
    return true;
}

void record(const TraceRow& row) {
    if (g_trace.size() < g_traceCap) g_trace.push_back(row);
}

// One-shot cursor step armed by the motion hook for exactly one move() call.
struct Pending {
    bool      armed = false;
    float     nx = 0, ny = 0;
    TraceRow* row = nullptr;
} g_pending;

// Each motion invocation owns the slot for its dynamic extent and restores the
// enclosing invocation's slot on exit (also on exceptions), so a nested motion
// can neither consume nor overwrite an outer step.
struct PendingScope {
    Pending saved;
    explicit PendingScope(Pending mine) : saved(g_pending) { g_pending = mine; }
    ~PendingScope() { g_pending = saved; }
    PendingScope(const PendingScope&)            = delete;
    PendingScope& operator=(const PendingScope&) = delete;
};

void hkMove(Pointer::CPointerManager* self, const Vector2D& stock) {
    const auto original = reinterpret_cast<MoveFn>(g_moveHook->m_original);
    if (!g_pending.armed) return original(self, stock);
    g_pending.armed = false;
    auto&      row    = *g_pending.row;
    const auto before = self->position();
    Vector2D   step{0, 0};
    if (g_pending.nx != 0 || g_pending.ny != 0) {
        double qx = before.x + double(g_pending.nx), qy = before.y + double(g_pending.ny);
        double fx, fy;
        if (g_quantize && fixed24_8(qx, fx) && fixed24_8(qy, fy))
            qx = fx, qy = fy;
        step = {qx - before.x, qy - before.y};
    }
    row.beforeX = before.x, row.beforeY = before.y, row.appliedX = step.x, row.appliedY = step.y;
    original(self, step);
}

void hkOnMouseMoved(CInputManager* self, IPointer::SMotionEvent e) {
    const auto original = reinterpret_cast<MotionFn>(g_hook->m_original);
    const bool selected = g_enabled && g_selftest && e.mouse && e.device && !e.device->m_isTouchpad &&
                          g_devices.contains(e.device->m_hlName);
    if (!selected) {
        PendingScope scope{Pending{}};
        if (g_traceCap) {
            ++g_other;
            const auto before = Pointer::mgr()->position();
            TraceRow row{++g_seq, e.timeMs, e.unaccel.x, e.unaccel.y, e.delta.x, e.delta.y, 0, 0, 0, 0,
                         before.x, before.y, e.delta.x, e.delta.y, 0, 0, 3, e.device ? e.device->m_hlName : ""};
            original(self, e);
            const auto after = Pointer::mgr()->position();
            row.afterX = after.x, row.afterY = after.y;
            record(row);
        } else
            original(self, e);
        return;
    }

    TraceRow row{++g_seq, e.timeMs, e.unaccel.x, e.unaccel.y, e.delta.x, e.delta.y, 0, 0, 0, 0,
                 0, 0, 0, 0, 0, 0, 0, e.device->m_hlName};
    const double rx = e.unaccel.x, ry = e.unaccel.y;
    // Admit only the integer count domain shared with the captured descriptor.
    if (rx != std::trunc(rx) || ry != std::trunc(ry) || std::fabs(rx) > 32767 || std::fabs(ry) > 32767) {
        ++g_refused;
        row.kind = 2;
        PendingScope scope{Pending{}};
        original(self, e);
        record(row);
        return;
    }
    const auto a = g_profiles[g_speed - 1].apply(rx, ry);
    const float nx = static_cast<float>(a[0]), ny = static_cast<float>(a[1]);
    row.tableX = a[0], row.tableY = a[1], row.nxX = nx, row.nxY = ny;
    row.kind = nx == 0 && ny == 0 ? 1 : 0;
    e.delta  = {double(nx), double(ny)};
    {
        PendingScope scope{Pending{true, nx, ny, &row}};
        original(self, e);
        if (g_pending.armed) // capture/inhibition paths never reached move()
            row.kind = 4;
    }
    ++(row.kind == 0 ? g_transformed : row.kind == 1 ? g_noMotion : g_unmoved);
    const auto after = Pointer::mgr()->position();
    row.afterX = after.x, row.afterY = after.y;
    record(row);
}

std::string status() {
    std::ostringstream o;
    o << "{\"enabled\":" << (g_enabled ? "true" : "false") << ",\"selftest\":" << (g_selftest ? "true" : "false")
      << ",\"quantize\":" << (g_quantize ? "true" : "false") << ",\"speed\":" << g_speed
      << ",\"scaling\":" << kSpeeds[g_speed - 1].scaling << ",\"devices\":[";
    bool first = true;
    for (const auto& d : g_devices) o << (first ? "" : ",") << '"' << d << '"', first = false;
    o << "],\"transformed\":" << g_transformed << ",\"no_motion\":" << g_noMotion << ",\"refused\":" << g_refused
      << ",\"other\":" << g_other << ",\"unmoved\":" << g_unmoved << ",\"trace_rows\":" << g_trace.size() << ",\"trace_cap\":" << g_traceCap << "}";
    return o.str();
}

bool dumpTrace(const std::string& path) {
    std::ofstream out(path);
    if (!out) return false;
    out << "seq,time_ms,kind,device,raw_x,raw_y,stock_x,stock_y,table_x,table_y,nx_x_bits,nx_y_bits,before_x,before_y,applied_x,applied_y,after_x,after_y\n";
    char buf[1024];
    for (const auto& r : g_trace) {
        std::snprintf(buf, sizeof buf, "%lu,%u,%d,%s,%a,%a,%a,%a,%a,%a,%08x,%08x,%a,%a,%a,%a,%a,%a\n", (unsigned long)r.seq, r.timeMs, r.kind,
                      r.device.c_str(), r.rawX, r.rawY, r.stockX, r.stockY, r.tableX, r.tableY, bits(r.nxX), bits(r.nxY), r.beforeX, r.beforeY,
                      r.appliedX, r.appliedY, r.afterX, r.afterY);
        out << buf;
    }
    return bool(out);
}

std::string command(eHyprCtlOutputFormat, std::string request);

// hyprctl macmouse status|enable|disable|quantize on|off|speed 1..10|devices a,b|pos|warp X Y|
//                  trace start N|trace dump PATH|trace stop
std::string command(eHyprCtlOutputFormat, std::string request) {
    std::istringstream in(request);
    std::vector<std::string> args;
    for (std::string w; in >> w;) args.push_back(w);
    if (!args.empty() && args[0] == "macmouse") args.erase(args.begin());
    const auto arg = [&](size_t i) { return i < args.size() ? args[i] : std::string(); };
    if (arg(0).empty() || arg(0) == "status") return status();
    if (arg(0) == "enable") return g_enabled = true, status();
    if (arg(0) == "disable") return g_enabled = false, status();
    if (arg(0) == "quantize" && (arg(1) == "on" || arg(1) == "off")) return g_quantize = arg(1) == "on", status();
    if (arg(0) == "speed") { // macOS tracking-speed slider tick: 1 = Slow ... 10 = Fast
        const auto& t = arg(1);
        if (t.empty() || t.size() > 2 || t.find_first_not_of("0123456789") != std::string::npos || std::stoi(t) < 1 || std::stoi(t) > 10)
            return "error: speed must be a tracking-speed tick from 1 (Slow) to 10 (Fast)";
        return g_speed = std::stoi(t), status();
    }
    if (arg(0) == "devices" && !arg(1).empty()) { // "-" selects none
        g_devices.clear();
        std::istringstream list(arg(1));
        for (std::string d; std::getline(list, d, ',');)
            if (!d.empty()) g_devices.insert(d);
        return status();
    }
    if (arg(0) == "pos") {
        const auto p = Pointer::mgr()->position();
        char       buf[128];
        std::snprintf(buf, sizeof buf, "%a %a", p.x, p.y);
        return buf;
    }
    if (arg(0) == "warp" && !arg(2).empty()) {
        Pointer::mgr()->warpTo({std::strtod(arg(1).c_str(), nullptr), std::strtod(arg(2).c_str(), nullptr)});
        return command(eHyprCtlOutputFormat{}, "pos");
    }
    if (arg(0) == "trace" && arg(1) == "start") {
        g_trace.clear();
        g_traceCap = std::min<size_t>(std::strtoull(arg(2).c_str(), nullptr, 10), 1000000);
        g_seq = g_transformed = g_noMotion = g_refused = g_other = g_unmoved = 0;
        g_trace.reserve(g_traceCap);
        return status();
    }
    if (arg(0) == "trace" && arg(1) == "stop") return g_traceCap = 0, g_trace.clear(), g_trace.shrink_to_fit(), status();
    if (arg(0) == "trace" && arg(1) == "dump" && !arg(2).empty()) return dumpTrace(arg(2)) ? status() : "error: cannot write " + arg(2);
    return "error: unknown macmouse command";
}
} // namespace

APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }

APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    g_handle = handle;
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash())
        throw std::runtime_error("macmouse: built against a different Hyprland; rebuild");
    g_selftest = selfTest();
    if (!g_selftest)
        HyprlandAPI::addNotification(handle, "[macmouse] self-test failed; passthrough only", CHyprColor{1.0, 0.2, 0.2, 1.0}, 10000);

    // Match exact mangled names: the demangled field of findFunctionsByName
    // results was observed paired with the wrong symbol on 0.56.2.
    const auto findHook = [&](const char* name, const char* mangled, void* destination) {
        CFunctionHook* found = nullptr;
        for (const auto& match : HyprlandAPI::findFunctionsByName(handle, name)) {
            if (match.signature != mangled) continue;
            if (found) throw std::runtime_error(std::string("macmouse: ambiguous ") + mangled);
            found = HyprlandAPI::createFunctionHook(handle, match.address, destination);
        }
        if (!found) throw std::runtime_error(std::string("macmouse: hook target not found: ") + mangled);
        return found;
    };
    CFunctionHook* hook     = findHook("onMouseMoved", "_ZN13CInputManager12onMouseMovedEN8IPointer12SMotionEventE", reinterpret_cast<void*>(&hkOnMouseMoved));
    CFunctionHook* moveHook = findHook("move", "_ZN7Pointer15CPointerManager4moveERKN9Hyprutils4Math8Vector2DE", reinterpret_cast<void*>(&hkMove));
    // Install the consumer before the producer so an armed step is never left unconsumed.
    g_moveHook = moveHook;
    g_hook     = hook;
    if (!moveHook->hook() || !hook->hook()) throw std::runtime_error("macmouse: cannot install hooks");

    HyprlandAPI::registerHyprCtlCommand(handle, SHyprCtlCommand{.name = "macmouse", .exact = false, .fn = command});
    return {"macmouse", "macOS 26.5 pointer transform for selected mice", "advait/macmouse", "1.0"};
}

APICALL EXPORT void PLUGIN_EXIT() {
    // Hyprland removes hooks and hyprctl commands owned by this handle.
    g_hook = g_moveHook = nullptr;
}
