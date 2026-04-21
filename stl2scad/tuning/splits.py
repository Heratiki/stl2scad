"""Deterministic splits for detector tuning experiments.

Why stratified: the manifest has 26 fixtures across 5 types with heavy class
imbalance (17 plate, 6 box, 1 each l_bracket/sphere/torus). A naive split
would often drop the singleton classes from train entirely — the tuner then
reassigns their thresholds freely and scores high for the wrong reason.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Iterator


def stratified_split(
    fixtures: list[dict],
    holdout_ratio: float = 0.25,
    seed: int = 42,
) -> tuple[list[dict], list[dict]]:
    rng = random.Random(seed)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for fixture in fixtures:
        by_type[fixture["fixture_type"]].append(fixture)

    train: list[dict] = []
    holdout: list[dict] = []
    for fixture_type, items in sorted(by_type.items()):
        shuffled = list(items)
        rng.shuffle(shuffled)
        # Singletons always go to train.
        holdout_count = int(round(len(shuffled) * holdout_ratio))
        if len(shuffled) <= 2:
            holdout_count = 0
        train.extend(shuffled[holdout_count:])
        holdout.extend(shuffled[:holdout_count])

    train.sort(key=lambda f: f["name"])
    holdout.sort(key=lambda f: f["name"])
    return train, holdout


def leave_one_out(fixtures: list[dict]) -> Iterator[tuple[list[dict], list[dict]]]:
    for index in range(len(fixtures)):
        holdout = [fixtures[index]]
        train = fixtures[:index] + fixtures[index + 1:]
        yield train, holdout
