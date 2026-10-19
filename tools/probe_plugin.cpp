#include <hyprland/src/config/shared/monitor/MonitorRuleManager.hpp>
#include <hyprland/src/plugins/PluginAPI.hpp>
#include <hyprland/src/managers/input/InputManager.hpp>
#include <hyprland/src/pointer/PointerManager.hpp>
#include <aquamarine/input/Input.hpp>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>

// Test-only plugin: refuses to load without an isolated-test opt-in.
// Emits motion events through Aquamarine/CMouse signals so they reach the
// hooked CInputManager::onMouseMoved in a nested compositor.
class ProbePointer : public Aquamarine::IPointer {
    std::string name = "macmouse-test-probe";
  public:
    libinput_device* getLibinputHandle() override { return nullptr; }
    const std::string& getName() override { return name; }
};
static SP<ProbePointer> pointer;
APICALL EXPORT std::string PLUGIN_API_VERSION() { return HYPRLAND_API_VERSION; }
APICALL EXPORT PLUGIN_DESCRIPTION_INFO PLUGIN_INIT(HANDLE handle) {
    const char* isolated = std::getenv("MACMOUSE_ISOLATED_TEST");
    if (!isolated || std::string(isolated) != "1") throw std::runtime_error("test compositor opt-in required");
    if (std::string(__hyprland_api_get_hash()) != __hyprland_api_get_client_hash()) throw std::runtime_error("Hyprland ABI mismatch");
    // Monitor keywords schedule work on render pre-checks. A nested window may
    // receive no parent frame callbacks; explicitly run the installed rule
    // manager in this isolated, ABI-checked test process instead.
    if (!HyprlandAPI::addDispatcherV2(handle, "macmousetest:monitors", [](std::string)->SDispatchResult {
        Config::monitorRuleMgr()->ensureMonitorStatus();
        return {.success=true,.error=""};
    })) throw std::runtime_error("monitor dispatcher registration");
    pointer = makeShared<ProbePointer>();
    g_pInputManager->newMouse(pointer);
    if (!HyprlandAPI::addDispatcherV2(handle, "macmousetest:coordinates", [](std::string arg) -> SDispatchResult {
        std::istringstream options(arg);
        std::string source, destination; double startX = 0, startY = 0;
        if (!(options >> source >> destination >> startX >> startY))
            return {.success = false, .error = "input.csv output.csv initialX initialY required"};
        std::ifstream input(source); std::ofstream output(destination);
        if (!input || !output) return {.success = false, .error = "cannot open probe files"};
        auto original = Pointer::mgr()->position();
        Pointer::mgr()->warpTo({startX, startY});
        std::string line; std::getline(input, line);
        output << "index,initial_x,initial_y,raw_x,raw_y,out_x,out_y,cursor_x,cursor_y\n" << std::setprecision(17);
        size_t rows = 0;
        while (std::getline(input, line)) {
            unsigned long index, time; double x, y, dx, dy;
            if (std::sscanf(line.c_str(), "%lu,%lf,%lf,%lf,%lf,%lu", &index, &x, &y, &dx, &dy, &time) != 6) {
                Pointer::mgr()->warpTo(original); return {.success = false, .error = "invalid input row"};
            }
            auto before = Pointer::mgr()->position();
            Aquamarine::IPointer::SMoveEvent event;
            event.timeMs = time / 1000; event.delta = {dx, dy}; event.unaccel = {x, y};
            pointer->events.move.emit(event);
            pointer->events.frame.emit();
            auto after = Pointer::mgr()->position();
            output << index << ',' << before.x << ',' << before.y << ',' << x << ',' << y << ',' << dx << ',' << dy << ',' << after.x << ',' << after.y << '\n';
            ++rows;
        }
        Pointer::mgr()->warpTo(original);
        return {.success = rows > 0, .error = rows ? "" : "empty probe"};
    })) throw std::runtime_error("cannot register coordinate dispatcher");
    return {"macmouse-test-probe", "Isolated test probe only", "advait/macmouse", "0.1"};
}
APICALL EXPORT void PLUGIN_EXIT() { pointer.reset(); }
