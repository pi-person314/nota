"""Unit tests for `nota.services.spanner_index`.

Two groups:

- Synthetic-score correctness/mechanics tests (patch/unpatch bookkeeping,
  cache invalidation on every mutator observed to run during a real export,
  reentrancy, exceptions, the disable toggle) -- fast, hand-built spanner
  graphs so exact result ordering can be pinned down precisely.
- Byte-identical output regression tests against real corpus scores: a
  fresh parse written once with the accelerator off and once on must
  produce the exact same MusicXML bytes, before any repair
  post-processing. This is the non-negotiable correctness gate for the
  whole module -- a discrepancy here would mean the exporter silently
  serialized a spanner differently because of the patched lookup.
"""

from __future__ import annotations

import music21 as m21
import pytest
from music21 import corpus
from music21 import spanner as m21_spanner

from nota.services import spanner_index

# ---------------------------------------------------------------------------
# synthetic scenarios
# ---------------------------------------------------------------------------


def _notes(n: int) -> list[m21.note.Note]:
    return [m21.note.Note("C4") for _ in range(n)]


def _ids(spanners) -> list[int]:
    return [id(sp) for sp in spanners]


def test_matches_original_scan_on_overlapping_spanners():
    """Several spanners share elements; the indexed lookup must return the
    exact same spanners in the exact same order as the original linear
    scan, for every queried element.
    """
    n1, n2, n3, n4 = _notes(4)
    su1 = m21_spanner.Slur(n1, n2)
    su2 = m21_spanner.Slur(n2, n3)
    su3 = m21_spanner.Slur(n1, n4)
    bundle = m21_spanner.SpannerBundle([su1, su2, su3])

    expected = {
        id(n): _ids(bundle.getBySpannedElement(n)) for n in (n1, n2, n3, n4)
    }

    with spanner_index.accelerated_spanner_lookup():
        actual = {
            id(n): _ids(bundle.getBySpannedElement(n)) for n in (n1, n2, n3, n4)
        }

    assert actual == expected
    assert expected[id(n1)] == [id(su1), id(su3)]
    assert expected[id(n2)] == [id(su1), id(su2)]
    assert expected[id(n3)] == [id(su2)]
    assert expected[id(n4)] == [id(su3)]


def test_repeated_queries_hit_the_same_index_and_agree():
    n1, n2 = _notes(2)
    su1 = m21_spanner.Slur(n1, n2)
    bundle = m21_spanner.SpannerBundle([su1])

    with spanner_index.accelerated_spanner_lookup():
        first = _ids(bundle.getBySpannedElement(n1))
        second = _ids(bundle.getBySpannedElement(n1))
        assert first == second == [id(su1)]


def test_element_with_no_spanners_returns_empty_bundle():
    n1, n2, n3 = _notes(3)
    su1 = m21_spanner.Slur(n1, n2)
    bundle = m21_spanner.SpannerBundle([su1])

    with spanner_index.accelerated_spanner_lookup():
        result = bundle.getBySpannedElement(n3)

    assert isinstance(result, m21_spanner.SpannerBundle)
    assert len(result) == 0


def test_spanner_referencing_same_element_twice_counts_once():
    """A spanner whose storage happens to contain the same element more
    than once must still only appear once in the result -- matching the
    original scan's `spannedElement in sp` (boolean) semantics.
    """
    n1, n2 = _notes(2)
    su1 = m21_spanner.Slur(n1, n2)
    # Force a duplicate entry directly into spanner storage, bypassing
    # addSpannedElements' own de-duplication, to exercise the edge case.
    su1.spannerStorage.coreAppend(n1)
    su1.spannerStorage.coreElementsChanged()
    bundle = m21_spanner.SpannerBundle([su1])

    with spanner_index.accelerated_spanner_lookup():
        result = _ids(bundle.getBySpannedElement(n1))

    assert result == [id(su1)]


# --- staleness: mutators observed to run during a real export -------------


def test_spanner_level_replace_invalidates_index_mid_context():
    """`Spanner.replaceSpannedElement` (called directly on a spanner, not
    through the bundle) is exactly what music21's own tuplet-bracket and
    tie-consolidation passes call during export. A lookup after this call
    must reflect the new element, and the old element must no longer
    match, even though the index was already built before the mutation.
    """
    n1, n2, n3 = _notes(3)
    su1 = m21_spanner.Slur(n1, n2)
    bundle = m21_spanner.SpannerBundle([su1])

    with spanner_index.accelerated_spanner_lookup():
        assert _ids(bundle.getBySpannedElement(n2)) == [id(su1)]  # builds the index

        su1.replaceSpannedElement(n2, n3)

        assert _ids(bundle.getBySpannedElement(n2)) == []
        assert _ids(bundle.getBySpannedElement(n3)) == [id(su1)]


def test_bundle_level_replace_invalidates_index_mid_context():
    n1, n2, n3, n4 = _notes(4)
    su1 = m21_spanner.Slur(n1, n2)
    su2 = m21_spanner.Slur(n2, n4)
    bundle = m21_spanner.SpannerBundle([su1, su2])

    with spanner_index.accelerated_spanner_lookup():
        assert _ids(bundle.getBySpannedElement(n2)) == [id(su1), id(su2)]

        bundle.replaceSpannedElement(n2, n3)

        assert _ids(bundle.getBySpannedElement(n2)) == []
        assert _ids(bundle.getBySpannedElement(n3)) == [id(su1), id(su2)]


def test_bundle_append_invalidates_index_mid_context():
    n1, n2 = _notes(2)
    su1 = m21_spanner.Slur(n1, n2)
    bundle = m21_spanner.SpannerBundle([su1])

    with spanner_index.accelerated_spanner_lookup():
        assert _ids(bundle.getBySpannedElement(n1)) == [id(su1)]  # builds the index

        su2 = m21_spanner.Slur(n1, n2)
        bundle.append(su2)

        assert _ids(bundle.getBySpannedElement(n1)) == [id(su1), id(su2)]


def test_bundle_remove_invalidates_index_mid_context():
    n1, n2 = _notes(2)
    su1 = m21_spanner.Slur(n1, n2)
    su2 = m21_spanner.Slur(n1, n2)
    bundle = m21_spanner.SpannerBundle([su1, su2])

    with spanner_index.accelerated_spanner_lookup():
        assert _ids(bundle.getBySpannedElement(n1)) == [id(su1), id(su2)]

        bundle.remove(su2)

        assert _ids(bundle.getBySpannedElement(n1)) == [id(su1)]


def test_replace_on_one_bundle_does_not_corrupt_an_unrelated_bundle():
    """`Spanner.replaceSpannedElement` cannot tell which bundle(s) hold the
    spanner it was called on, so the implementation conservatively drops
    every currently-built index. That must only force a rebuild elsewhere
    -- it must never change what an unrelated bundle reports.
    """
    n1, n2, n3, n4 = _notes(4)
    su_a = m21_spanner.Slur(n1, n2)
    bundle_a = m21_spanner.SpannerBundle([su_a])
    su_b = m21_spanner.Slur(n3, n4)
    bundle_b = m21_spanner.SpannerBundle([su_b])

    with spanner_index.accelerated_spanner_lookup():
        assert _ids(bundle_a.getBySpannedElement(n1)) == [id(su_a)]
        assert _ids(bundle_b.getBySpannedElement(n3)) == [id(su_b)]

        su_a.replaceSpannedElement(n1, n2)  # unrelated to bundle_b entirely

        assert _ids(bundle_b.getBySpannedElement(n3)) == [id(su_b)]
        assert _ids(bundle_b.getBySpannedElement(n4)) == [id(su_b)]


# --- context manager mechanics ---------------------------------------------


def test_restores_original_after_normal_exit():
    original = m21_spanner.SpannerBundle.getBySpannedElement
    with spanner_index.accelerated_spanner_lookup():
        assert m21_spanner.SpannerBundle.getBySpannedElement is not original
    assert m21_spanner.SpannerBundle.getBySpannedElement is original


def test_restores_original_after_exception():
    original = m21_spanner.SpannerBundle.getBySpannedElement
    with pytest.raises(RuntimeError):
        with spanner_index.accelerated_spanner_lookup():
            assert m21_spanner.SpannerBundle.getBySpannedElement is not original
            raise RuntimeError("boom")
    assert m21_spanner.SpannerBundle.getBySpannedElement is original


def test_nested_context_managers_do_not_double_patch_or_restore_early():
    original = m21_spanner.SpannerBundle.getBySpannedElement
    with spanner_index.accelerated_spanner_lookup():
        patched = m21_spanner.SpannerBundle.getBySpannedElement
        assert patched is not original
        with spanner_index.accelerated_spanner_lookup():
            # Inner entry must not re-patch (would restore the wrong
            # "original" -- the outer patch -- on its own exit otherwise).
            assert m21_spanner.SpannerBundle.getBySpannedElement is patched
        # Inner exit must leave the outer block still patched.
        assert m21_spanner.SpannerBundle.getBySpannedElement is patched
    assert m21_spanner.SpannerBundle.getBySpannedElement is original


def test_nested_context_managers_restore_correctly_through_exception_in_inner():
    original = m21_spanner.SpannerBundle.getBySpannedElement
    with spanner_index.accelerated_spanner_lookup():
        with pytest.raises(RuntimeError):
            with spanner_index.accelerated_spanner_lookup():
                raise RuntimeError("boom")
        # Outer block must still be patched after the inner one unwound.
        assert m21_spanner.SpannerBundle.getBySpannedElement is not original
    assert m21_spanner.SpannerBundle.getBySpannedElement is original


def test_disable_env_var_skips_the_patch(monkeypatch):
    monkeypatch.setenv("SPANNER_INDEX_DISABLE", "1")
    original = m21_spanner.SpannerBundle.getBySpannedElement
    with spanner_index.accelerated_spanner_lookup():
        assert m21_spanner.SpannerBundle.getBySpannedElement is original


def test_disable_env_var_read_fresh_on_every_entry(monkeypatch):
    original = m21_spanner.SpannerBundle.getBySpannedElement

    monkeypatch.setenv("SPANNER_INDEX_DISABLE", "1")
    with spanner_index.accelerated_spanner_lookup():
        assert m21_spanner.SpannerBundle.getBySpannedElement is original

    monkeypatch.delenv("SPANNER_INDEX_DISABLE")
    with spanner_index.accelerated_spanner_lookup():
        assert m21_spanner.SpannerBundle.getBySpannedElement is not original
    assert m21_spanner.SpannerBundle.getBySpannedElement is original


def test_bundle_used_both_inside_and_outside_the_with_block():
    """A bundle queried before entering the accelerated block (against the
    real implementation), then again inside it, then again after exiting,
    must give consistent, correct answers throughout -- no leftover index
    from the accelerated section may leak into unpatched use afterward.
    """
    n1, n2, n3 = _notes(3)
    su1 = m21_spanner.Slur(n1, n2)
    bundle = m21_spanner.SpannerBundle([su1])

    before = _ids(bundle.getBySpannedElement(n1))

    with spanner_index.accelerated_spanner_lookup():
        during = _ids(bundle.getBySpannedElement(n1))
        su1.replaceSpannedElement(n2, n3)
        during_after_replace = _ids(bundle.getBySpannedElement(n3))

    after = _ids(bundle.getBySpannedElement(n3))

    assert before == during == [id(su1)]
    assert during_after_replace == after == [id(su1)]
    assert len(bundle.getBySpannedElement(n2)) == 0


def test_multiple_bundles_indexed_concurrently_stay_independent():
    n1, n2, n3, n4 = _notes(4)
    su_a = m21_spanner.Slur(n1, n2)
    bundle_a = m21_spanner.SpannerBundle([su_a])
    su_b1 = m21_spanner.Slur(n3, n4)
    su_b2 = m21_spanner.Slur(n1, n4)  # shares n1's id space with bundle_a's note
    bundle_b = m21_spanner.SpannerBundle([su_b1, su_b2])

    with spanner_index.accelerated_spanner_lookup():
        assert _ids(bundle_a.getBySpannedElement(n1)) == [id(su_a)]
        assert _ids(bundle_b.getBySpannedElement(n1)) == [id(su_b2)]
        assert _ids(bundle_b.getBySpannedElement(n4)) == [id(su_b1), id(su_b2)]
        # bundle_a never had su_b1/su_b2 in it; re-check after bundle_b's
        # own lookups to make sure nothing bled across.
        assert _ids(bundle_a.getBySpannedElement(n1)) == [id(su_a)]


# ---------------------------------------------------------------------------
# byte-identical output against real corpus scores
# ---------------------------------------------------------------------------

# Every corpus id `tests/tools/real_score_builders.py` uses, plus the two
# scores explicitly named for this accelerator: haydn/opus74no1/movement3
# (already covered by REAL_SCORE_BUILDERS below, kept explicit for
# visibility) and beethoven/opus133 (the large, spanner-heavy score the
# accelerator was built for -- not part of the tool-pipeline fixture set,
# since its own writer-output shape isn't otherwise exercised elsewhere).
_CORPUS_IDS = [
    "bach/bwv1.6",
    "mozart/k545/movement1_exposition",
    "schoenberg/opus19/movement6",
    "schumann_robert/opus41no1/movement3",
    "haydn/opus74no1/movement3",
    "beethoven/opus18no1/movement1",
    "beethoven/opus133",
]


def _deterministic_md5(monkeypatch) -> None:
    """music21's writer deliberately mints a fresh random id (via
    `common.getMd5()`, called with no argument, seeded from wall-clock time
    plus `random.random()`) for every part/instrument it exports
    (`Instrument.partIdRandomize` / `instrumentIdRandomize`, called from
    `m21ToXml.py`) -- by design, not a bug, and completely unrelated to
    spanner lookup. Left alone, that alone would make two independent
    writes of the same score differ, regardless of this module's patch.

    `common.getMd5` is also used, called *with* a value, as a genuine
    content hash for unrelated purposes (`freezeThaw`'s on-disk corpus
    cache keys content by `getMd5(streamStr)`) -- faking that path too,
    rather than passing it through to the real implementation, corrupts
    that cache's keys and can make `corpus.parse()` return a completely
    different cached work than the one asked for. So only the no-argument
    (random id) call is replaced, with a deterministic counter reset
    before each write; every content-hash call keeps using the real
    implementation.
    """
    counter = iter(range(1, 10_000))
    real_get_md5 = m21.common.getMd5

    def fake_get_md5(value=None):
        if value is not None:
            return real_get_md5(value)
        return f"{next(counter):032x}"

    monkeypatch.setattr(m21.common, "getMd5", fake_get_md5)


def _write_bytes(
    corpus_id: str, tmp_path, suffix: str, *, accelerated: bool, monkeypatch
) -> bytes:
    # Fresh parse each time: export mutates the in-memory score (makeNotation,
    # tie consolidation, ...), so reusing one parsed object across the
    # off/on comparison would not isolate the accelerator's effect.
    score = corpus.parse(corpus_id)
    _deterministic_md5(monkeypatch)
    out_path = tmp_path / f"{suffix}.musicxml"
    if accelerated:
        with spanner_index.accelerated_spanner_lookup():
            score.write("musicxml", fp=str(out_path))
    else:
        score.write("musicxml", fp=str(out_path))
    return out_path.read_bytes()


@pytest.mark.parametrize("corpus_id", _CORPUS_IDS)
def test_byte_identical_output_with_and_without_accelerator(corpus_id, tmp_path, monkeypatch):
    off_bytes = _write_bytes(corpus_id, tmp_path, "off", accelerated=False, monkeypatch=monkeypatch)
    on_bytes = _write_bytes(corpus_id, tmp_path, "on", accelerated=True, monkeypatch=monkeypatch)
    assert on_bytes == off_bytes
