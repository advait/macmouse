# Strict IEEE binary64: no contraction, no fast-math. The model calls std::fma
# exactly where Apple's binary uses FMADD.
CXX      ?= g++
FPFLAGS  := -O2 -ffp-contract=off -fno-fast-math -Wall -Wextra
HYPRFLAGS = $$(pkg-config --cflags hyprland pixman-1 libdrm)

.PHONY: all plugin check verify nested install uninstall clean
all: check plugin

build:
	mkdir -p build

# Portable model vs Apple's recorded outputs at every tracking speed; runs anywhere (no Hyprland needed).
build/check_model: tests/check_model.cpp src/pointer_profile.hpp build/macmouse_table.inc
	$(CXX) -std=c++17 $(FPFLAGS) -Isrc -Ibuild $< -o $@
check: build/check_model
	build/check_model tests/vectors/speed-*.csv.gz

build/macmouse_table.inc: profiles/tracking-speeds.hex.csv | build
	awk -F, 'NR==1{if($$0!="tick,scaling,m,b,x")exit 1;print "constexpr mouse_parity::Segment kSegments[] = {";next}\
	  {print "    {"$$3", "$$4", "$$5"},";if($$1!=t){t=$$1;n++;tk[n]=$$1;sc[n]=$$2;f[n]=NR-2}c[n]++}\
	  END{print "};\nconstexpr mouse_parity::TrackingSpeed kSpeeds[] = {";for(i=1;i<=n;i++)print "    {"tk[i]", "sc[i]", "f[i]", "c[i]"},";print "};"}' $< > $@

build/macmouse.so: src/macmouse.cpp src/pointer_profile.hpp build/macmouse_table.inc
	$(CXX) -std=c++23 $(FPFLAGS) -fPIC -shared -Isrc -Ibuild $< -o $@ $(HYPRFLAGS)
build/probe_plugin.so: tools/probe_plugin.cpp | build
	$(CXX) -std=c++23 $(FPFLAGS) -fPIC -shared $< -o $@ $(HYPRFLAGS)
plugin: build/macmouse.so build/probe_plugin.so

# Isolated: new nested Hyprland, synthetic events, terminated afterwards.
nested: plugin
	python3 tools/nested_check.py
# Live session: uinput virtual mouse through kernel/libinput/Hyprland (~10 s, moves the cursor).
verify:
	python3 tools/live_verify.py

install: check plugin
	tools/install.sh
uninstall:
	tools/uninstall.sh
clean:
	rm -rf build
