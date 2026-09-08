# IO and IOLOGIC timing on GW5AST-138C: why the `.tm` has none

`P3.T32`. Companion to `doc/timing-c1i0.md` (grade derivation) and to the PLL
note in `apycula/tm_parser.py` (`P1.T33`).

## The two blocks

`tm_parser.offsets` places two IO-related groups in each 15552-byte chunk:

| group      | offset  | length | shape                                                      |
|------------|---------|--------|------------------------------------------------------------|
| `iregoreg` | `0x306c` | 524 B  | 2 paths, 3 reserved words, then 30 paths (4 floats each)   |
| `io`       | `0x3278` | 1200 B | 5 records of 240 B, one populated path at record `+0x8`     |

Both shapes are determinate and reproduce on GW1N-9, GW1NR-9, GW2A-18, GW2A-55,
GW2AR-18, GW5A-25A, GW5AT-60B and GW5AST-138C. `io_block()` and
`iregoreg_block()` decode them under positional `path_n` names.

## Measurement 1 — the bytes are inherited GW2A data

SHA-256 (first 12 hex digits) of each block, chunk by chunk:

| device        | chunk | `iregoreg`     | `io`           |
|---------------|-------|----------------|----------------|
| GW5AST-138C   | 0, 1  | `05b78b8765ef` | `548846ce8c8b` |
| GW5A-25A      | 0, 1  | `05b78b8765ef` | `548846ce8c8b` |
| GW5AT-60B     | 0, 1  | `05b78b8765ef` | `548846ce8c8b` |
| GW2A-18/-55   | 0, 1  | `05b78b8765ef` | `548846ce8c8b` |
| GW2AR-18      | 0, 1  | `05b78b8765ef` | `548846ce8c8b` |
| GW1N-9        | 0     | `79114382e19d` | `89d0043aab4f` |

GW5AST-138C chunk 0 differs from GW2A-18 chunk 0 in **81 bytes, all of them at
or after offset `0x3738`** — that is, only the `iodelay` / `wire` / `fanout` /
`glbsrc` / `hclk` tail was re-characterised for the GW5A family. The IO and IO
register blocks were carried over from GW2A untouched. Chunk 2 is chunk 0
scaled by 0.86 (`P0.T36`), so it carries no independent IO measurement either.

## Measurement 2 — the numbers do not describe this die

Vendor SDF, GW5AST-LV138PG484AC1/I0, `-device_version C`, default (worst-case)
condition, `max` field (`D24`, `D49f`); from the `p3t11/{oddr,iddr}-pair` and
`p3t12/p3-oddr-iddr-io_basic-*` batches:

| vendor arc            | ns             | closest `.tm` candidate            | verdict |
|-----------------------|----------------|------------------------------------|---------|
| `IBUF I->O`           | 0.619          | `io path_4` 0.663                  | +7 %, but see below |
| `OBUF I->O`           | 2.528, 2.737   | `io` block maximum 0.819           | off by >3x |
| `ODDR CLK->Q0/Q1`     | 1.160, 1.146   | `iregoreg path_22/23` 1.019, 1.213 | -12 %, +6 % |
| `IDDR CLK->Q0/Q1`     | 0.572, 0.486   | `iregoreg path_14/15` 0.635, 0.831 | +11 %, +71 % |
| `IDDRC CLEAR->Q0/Q1`  | 0.748, 0.565   | no candidate of that shape         | unmapped |
| `ODDRC CLEAR->Q0/Q1`  | 1.092, 1.160   | no candidate of that shape         | unmapped |

The `OBUF` row settles it on its own: the whole `io` block's largest value is
0.819 ns, so no scaling of it produces an output-buffer arc. On the register
side no assignment of the three clock-to-out candidate pairs to the vendor's
`ODDR`/`IDDR` arcs lands inside the ±10 % L0 band. A single `IBUF` value that
happens to fall within band is a coincidence of range, not a mapping.

## Consequence

`parse_io` and `parse_iregoreg` publish **nothing** and return the `NoData`
sentinel with the reasons above, exactly as `parse_pll` does for the inherited
rPLL block at `0x7cc`. `create_timing_info` in nextpnr has branches for both
group names that carry the same marker and emit no arc, so a future `.tm` that
starts publishing real data fails loudly rather than passing unnoticed.

This is **not** a claim that the 138C has no IO timing anywhere. `read_tm`
deliberately stops before chunk 3, which is the device-specific payload
(`P0.T36`). Whether the payload carries a real IO table is Phase 6's question
(`S17b`); this task must not widen the break to find out.
