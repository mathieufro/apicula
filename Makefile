ifndef GOWINHOME
# The local blocking gate (C8, D76-D77) must not die on this guard before it
# even gets a chance to export GOWINHOME itself (F87) -- gate.mk sources
# gate.env, so only the non-gate goals (all, clean, the msgpack.xz rule) are
# still required to have GOWINHOME set on entry.
ifeq (,$(filter gate,$(MAKECMDGOALS)))
$(error GOWINHOME is not set. Must be location of Gowin EDA Tools)
endif
endif

.SECONDARY:
.PHONY: all clean

include gate.mk

all: apycula/GW1N-1.msgpack.xz apycula/GW1N-9.msgpack.xz apycula/GW1N-4.msgpack.xz \
	 apycula/GW1NS-4.msgpack.xz apycula/GW1N-9C.msgpack.xz apycula/GW1NZ-1.msgpack.xz \
	 apycula/GW1N-2.msgpack.xz \
	 apycula/GW2A-18.msgpack.xz apycula/GW2A-18C.msgpack.xz apycula/GW5A-25A.msgpack.xz \
	 apycula/GW5AST-138C.msgpack.xz apycula/GW5AT-60B.msgpack.xz

BUILDER_DEPS = apycula/chipdb_builder.py apycula/fse_parser.py apycula/dat_parser.py \
               apycula/tm_parser.py apycula/chipdb.py

apycula/%.msgpack.xz: $(BUILDER_DEPS)
	python3 -m apycula.chipdb_builder $*

clean:
	rm -f apycula/*.msgpack.xz
