"""Real, complex scores pulled from the music21-bundled corpus, used to
stress the notation-tool pipeline beyond the small hand-built fixtures in
`musicxml_builders.py`.

Kept in a separate module (and a separate `REAL_SCORE_BUILDERS` dict) rather
than merged into `FIXTURE_BUILDERS` because real scores don't share the
synthetic fixtures' contract that measure 1 always has notes on beats 1 and
2 — the generic per-fixture sweep in `test_fixtures_and_rendering.py`
depends on that contract and iterates `FIXTURE_BUILDERS` specifically, so
merging these in would silently break it (e.g. the Mozart excerpt below has
no note on measure 1 beat 2). Real-score tests pick edge locations by
inspecting each piece's actual content instead.

Every builder here just calls `music21.corpus.parse(...)` on a work bundled
with the installed music21 package (no network access, no extra data
checked into this repo) and returns the Score unmodified. Picked for
specific real-world shapes the synthetic fixtures can't exercise:

- bach_bwv1_6: a 5-part chorale (one part doubles the soprano at the
  octave) with a one-beat pickup measure (numbered 0, the conventional
  way) — real multi-part writing plus the standard pickup shape.
- mozart_k545_exposition: a 2-staff piano excerpt with block chords in the
  left-hand staff — chords in a real keyboard texture, addressed as a
  second "part".
- schoenberg_op19_no6: extremely dense, atonal piano writing with up to 12
  simultaneous notated voices in one staff. Its first measure is numbered
  1 (not 0) but still carries `paddingLeft` — a pickup notated under a
  different real-world convention than the fixtures elsewhere in this
  suite use.
- schumann_op41no1_mvt3: a string quartet movement with a mid-piece meter
  change (2/2 -> 6/8 at measure 34).
- haydn_op74no1_mvt3: a string quartet movement dense with crescendo/
  decrescendo hairpins, kept modest in size (113 measures) specifically to
  exercise the tool pipeline's own draw_hairpin/remove_notation logic
  against a real score that already has many hairpins of its own.
- beethoven_op18no1_mvt1: a full 313-measure string quartet movement — the
  "large real score" case, and one with entire measures of rest in an
  inner part (the cello sits out several measures), which the small
  synthetic fixtures never exercise.
"""

from __future__ import annotations

import music21 as m21
from music21 import corpus


def build_bach_bwv1_6() -> m21.stream.Score:
    return corpus.parse("bach/bwv1.6")


def build_mozart_k545_exposition() -> m21.stream.Score:
    return corpus.parse("mozart/k545/movement1_exposition")


def build_schoenberg_op19_no6() -> m21.stream.Score:
    return corpus.parse("schoenberg/opus19/movement6")


def build_schumann_op41no1_mvt3() -> m21.stream.Score:
    return corpus.parse("schumann_robert/opus41no1/movement3")


def build_haydn_op74no1_mvt3() -> m21.stream.Score:
    return corpus.parse("haydn/opus74no1/movement3")


def build_beethoven_op18no1_mvt1() -> m21.stream.Score:
    return corpus.parse("beethoven/opus18no1/movement1")


REAL_SCORE_BUILDERS = {
    "bach_bwv1_6": build_bach_bwv1_6,
    "mozart_k545_exposition": build_mozart_k545_exposition,
    "schoenberg_op19_no6": build_schoenberg_op19_no6,
    "schumann_op41no1_mvt3": build_schumann_op41no1_mvt3,
    "haydn_op74no1_mvt3": build_haydn_op74no1_mvt3,
    "beethoven_op18no1_mvt1": build_beethoven_op18no1_mvt1,
}
