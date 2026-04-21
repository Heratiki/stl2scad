from pathlib import Path

from stl2scad.core.feature_fixtures import load_feature_fixture_manifest
from stl2scad.tuning.splits import stratified_split, leave_one_out


def _manifest():
    return load_feature_fixture_manifest(Path("tests/data/feature_fixtures_manifest.json"))


def test_stratified_split_is_disjoint_and_deterministic():
    fixtures = _manifest()
    train_a, holdout_a = stratified_split(fixtures, holdout_ratio=0.25, seed=42)
    train_b, holdout_b = stratified_split(fixtures, holdout_ratio=0.25, seed=42)
    assert [f["name"] for f in train_a] == [f["name"] for f in train_b]
    assert [f["name"] for f in holdout_a] == [f["name"] for f in holdout_b]
    train_names = {f["name"] for f in train_a}
    holdout_names = {f["name"] for f in holdout_a}
    assert train_names.isdisjoint(holdout_names)
    assert train_names | holdout_names == {f["name"] for f in fixtures}


def test_stratified_split_covers_every_type_in_holdout_when_possible():
    fixtures = _manifest()
    _train, holdout = stratified_split(fixtures, holdout_ratio=0.25, seed=42)
    types_in_holdout = {f["fixture_type"] for f in holdout}
    # sphere and torus are singletons — they MUST land in train (else the
    # detector never learns they exist). Plate/box/l_bracket can appear
    # in holdout.
    assert "sphere" not in types_in_holdout
    assert "torus" not in types_in_holdout


def test_leave_one_out_iterates_all():
    fixtures = _manifest()
    folds = list(leave_one_out(fixtures))
    assert len(folds) == len(fixtures)
    for train, holdout in folds:
        assert len(holdout) == 1
        assert len(train) == len(fixtures) - 1
