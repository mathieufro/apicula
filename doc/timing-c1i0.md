# The GW5A `C1/I0` speed grade is derived, not parsed

`GW5AST-LV138PG484AC1/I0` — the part this work targets — ships only in speed
grade **C1/I0**. nextpnr picks that grade straight out of the part string
(`himbaechel/uarch/gowin/gowin.cc:205,211,214`, regex `(C[0-9]/I[0-9])$`) and
calls `set_speed_grade("C1/I0")`. Whatever `db.timing["C1/I0"]` holds is
therefore what the entire open flow uses for static timing on this device.

## What the `.tm` file actually contains

`GW5AST-138C.tm` (Gowin EDA Standard 1.9.12.03) is 3,139,786 bytes. The parser
reads it as a flat sequence of 15,552-byte chunks from offset 0 — there is no
header and no index — which gives 201 whole chunks plus a 13,834-byte tail.
Only the first three decode as timing tables:

| chunk | md5 (first 12) | `lut.a_f` | `dff.lsr_q` | `dff.clk_qpos` | label |
|---|---|---|---|---|---|
| 0 | `02634de18c33` | 0.384 0.344 0.549 0.517 | 1.097 1.075 1.148 1.132 | 0.202 0.201 0.231 0.232 | `C2/I1` |
| 1 | `7c6360ec205f` | 0.429 0.397 0.429 0.397 | 1.097 1.075 1.148 1.132 | 0.202 0.201 0.231 0.232 | `unidentified_1` |
| 2 | `6d5f7bce7f74` | 0.331 0.297 0.473 0.446 | 0.946 0.927 0.990 0.976 | 0.174 0.173 0.199 0.200 | `unidentified_2` |
| 3+ | — | 2.0e-04 6.1e-04 6.0e+19 1.3e-05 | 3.3e+12 -1.4e+19 … | … | not chunk-formatted |

From chunk 3 on the same offsets decode as denormals, infinities and values of
order 1e+37 — the file is not a 202-entry chunk array (`P0.T36`: every chunk
from 3 on has a distinct md5 and a *different* md5 per device, so the tail is
device-specific data on another layout, not padding), and `read_tm`'s
`if i >= 3 and device in {...}: break` (`apycula/tm_parser.py:344`) is what
stops the parser before that garbage. That break is **not** touched here; it is
Phase 6's (`S17b`).

Chunk 1 carries chunk 0's DFF numbers with different LUT numbers; chunk 2 is a
uniform **0.862x** scaling of chunk 0 across every parsed group. Neither matches
a published grade column, so neither is published under a grade key. `P0.T36`
measured both (below) and **confirmed** that neither is a DS1239E column, so the
`unidentified_*` labels stand and `C1/I0` stays derived; **renaming them is not
done in this phase**, because a key rename changes what `set_speed_grade` can
select.

## What `P0.T36` measured (`D49b`, the first `W-TIMING` measurement)

Full dump, cross-device sweep and per-chunk evidence:
`$PIPE/evidence/timing-l0-cfu/chunks.md`. The four load-bearing results:

1. **Chunk 0 = C2/I1, high confidence.** `dff.lsr_q` min/max are *exactly*
   DS1239E `tSR_CFU` C2/I1 (1.075 / 1.148), and those two literals occur
   nowhere else in the 1,944 float scalars of chunks 0-2. `tCO_CFU` agrees to
   0.002 ns. The discriminator against chunk 1 is the LUT: the published
   `tLUT4_CFU` C2/I1 max of 0.539 is bracketed by chunk 0 (0.549 / 0.570) but
   is out of chunk 1's reach (max 0.440).
2. **Chunk 1 is not a grade.** 540 of its 648 float scalars are byte-equal to
   chunk 0; the 108 that move are exactly `lut` (44/44), `alu` (32/32),
   `sram.rad*_do` (16) and `wire` (16) -- `dff`, `bram`, `glbsrc`, `hclk`,
   `iodelay` and `fanout` are identical. All 27 tuples it moves *collapse*
   (slot[2]==slot[0], slot[3]==slot[1]): no min/max spread. The F-to-OFX1 mux
   delay is redistributed (`m0_ofx0` 0.189 + `fx_ofx1` 0.060 becomes
   0.076 + 0.213), i.e. a different model of the same silicon. Stays
   `unidentified_1`.
3. **Chunk 2 is not a grade either.** It is exactly `0.862 x` chunk 0 on 607 of
   608 non-zero, non-`fanout` scalars (the exception, `iodelay.SDTAP_DO`, is a
   tap constant); the `fanout` group is not scaled. A uniformly scaled table is
   a *derived* table, and DS1239E admits only two ratios, 1.00 and 1.25 -- and
   0.862x is *faster* than the fastest grade the part ships (DS1239E §4.1:
   "C2/I1 Fastest"). The two surviving hypotheses -- a higher core-voltage
   corner (the part is 0.9 V / 1.0 V, and this parser's GW1N chunk order already
   alternates `<grade>`/`<grade>_LV`) or a typical/fast process corner -- are
   separated by `S17b`'s L1 vendor-STA measurement, not by the file. Stays
   `unidentified_2`.
4. **Chunks 0-2 are a family-generic preamble, not a grade array.** GW5AT-60ES
   (one published grade, ES) and GW5A-25A (four, including A0) carry the
   identical three chunks, as does a GW3A part; chunk 3 onward has a distinct
   md5 for every device (198/198 distinct within GW5AST-138C alone) and only
   31-57 % of its floats land in a plausible delay range. So the tail is
   device-specific payload on a layout this parser does not know -- not
   all-denormal, not constant -- and opening it stays behind `D24`'s gate.

`P0.T36` made **no source edit**: no chunk was identified as `C1/I0`, so the
`1.25 x` derivation below is confirmed rather than replaced, and no
`unidentified_*` label earned a rename.

The three parsed chunks are byte-identical across **every** GW5-family `.tm`
Gowin EDA Standard 1.9.12.03 ships (22 devices, GW5A-25A / GW5AT-60B /
GW5AST-138B / GW5AST-138C among them) **and** across the two GW3A parts, and
they did not change between IDE 1.9.11.03 and 1.9.12.03. The model is
family-generic, and whether that is adequate for the 138K die is what the L0
measurement (`D49d`) tests.

## The bug this replaces

```python
_aliases = {"gw5a": {"ES": ["C1/I0", "A0"]}}
chunk_order = ["ES", "C2/I1", "3", ...]
```

Chunk 0 was labelled `ES` and copied verbatim onto `C1/I0` (and `A0`); chunk 1
got the `C2/I1` label and chunk 2 fell through to the filler label `"3"`. So
`db.timing["C1/I0"]` was chunk 0 — but chunk 0's numbers are the **C2/I1**
column of DS1239E Table 3-13:

| DS1239E Table 3-13 (CFU) | C2/I1 min–max | C1/I0 min–max | chunk 0 min–max |
|---|---|---|---|
| tLUT4_CFU | 0.297–0.539 | 0.371–0.674 | 0.344–0.549 |
| tSR_CFU (`dff.lsr_q`) | 1.075–1.148 | 1.344–1.435 | 1.075–1.148 |
| tCO_CFU (`dff.clk_qpos`) | 0.200–0.230 | 0.250–0.288 | 0.201–0.232 |

Every cell arc the open flow reported for this part was therefore ~25 %
optimistic before any routing error, silently.

## The derivation

DS1239E Table 3-13 (CFU) and Table 3-14 (BSRAM) both give **C1/I0 = 1.25 x
C2/I1** on every published row — 0.371/0.297, 0.674/0.539, 1.344/1.075,
1.435/1.148, 0.250/0.200, 0.288/0.230, 1.375/1.1, 1.838/1.47, 0.288/0.23,
0.408/0.326 all round to 1.25. The ratio is taken from **our own device's**
datasheet, not extrapolated from a GW5A-25 sheet. The `.tm` file carries no
C1/I0 chunk at all, so:

```
C1/I0 = 1.25 x (chunk 0, published as C2/I1)
```

applied to every float in every parsed group (`_scale`, `C1_I0_FROM_C2_I1`, in
`apycula/tm_parser.py`). `parse_fanout`'s integer fanout *counts*
(`X0FanNum` …) are topology, not delays, and are carried through unscaled.

**Agreement is to ~0.002 ns, not exact.** Chunk 0 itself sits slightly outside
the published C2/I1 band (`clk_qpos` max 0.232 vs 0.230; `lut.a_f` max 0.549 vs
0.539), presumably datasheet rounding, and the 1.25x carries that offset into
the derived table (`clk_qpos` max 0.290 vs a published 0.288). The `V7`
regression test allows 0.005 ns for this — two orders of magnitude tighter than
the 25 % gap it must separate.

**This is a regression test, not an acceptance test.** Multiplying a
datasheet-matching table by a datasheet-derived ratio and then checking it
against the datasheet is circular. What actually accepts the table is `S17b`'s
L0 measurement: the derived arcs within ±10 % of the vendor `.sdf` for the same
cells on this device (`D49c`).

## Resulting keys for `GW5AST-138C`

`{"C2/I1", "C1/I0", "unidentified_1", "unidentified_2"}` — exactly two of them
grade names. `'ES'` and `'A0'` no longer exist, so `set_speed_grade` cannot
land on a non-derived table; `gowin.cc:216-219`'s `ES` fallback is unreachable
for this part.

Test: `tests/test_timing_c1i0.py` (`V7`, `S17a`).

## What the built chipdb carries

`python -m apycula.chipdb_builder GW5AST-138C` (Gowin EDA Standard 1.9.12.03)
now stores `db.timing` with exactly these four keys — two grades, two
placeholders — where it previously stored five, three of which were the same
table under three names:

| key | `lut.a_f` (ns) | `dff.lsr_q` (ns) | `dff.clk_qpos` (ns) |
|---|---|---|---|
| `C1/I0` (derived, 1.25x) | 0.480 0.430 0.686 0.646 | 1.371 1.344 1.435 1.415 | 0.253 0.251 0.289 0.290 |
| `C2/I1` (chunk 0, measured) | 0.384 0.344 0.549 0.517 | 1.097 1.075 1.148 1.132 | 0.202 0.201 0.231 0.232 |
| `unidentified_1` (chunk 1) | 0.429 0.397 0.429 0.397 | 1.097 1.075 1.148 1.132 | 0.202 0.201 0.231 0.232 |
| `unidentified_2` (chunk 2) | 0.331 0.297 0.473 0.446 | 0.946 0.927 0.990 0.976 | 0.174 0.173 0.199 0.200 |

Before this change the same build produced `{'ES', 'C1/I0', 'A0', 'C2/I1',
'3'}`, with `ES`/`C1/I0`/`A0` all equal to chunk 0 (the row now labelled
`C2/I1`) and the `C2/I1` label attached to chunk 1 (now `unidentified_1`) — so
the old table *named* `C2/I1` was not the C2/I1 data either.

`parse_fanout`'s integer counts survive the scaling untouched
(`fanout.X0FanNum == 22` under both grades).

## Pre-GW5 devices are unaffected

`tests/test_tm_pre_gw5_regression.py` parses `GW1N-9C.tm` and `GW2A-18C.tm`
with this parser and with the untouched upstream `apycula==0.33` module loaded
from `$FL/vendor/venv-upstream`, and asserts the two results are identical
(compared by `repr`, since the filler tables past the real ones decode to NaN
on both sides and `NaN != NaN`). `_aliases` never held a GW1N/GW2A entry and
their `chunk_order` lists are untouched, so the change is GW5A-only by
construction; the test is the proof.
