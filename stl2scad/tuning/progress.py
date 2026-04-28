"""Best-effort progress feedback for local corpus tooling."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import TypeVar


T = TypeVar("T")


def corpus_progress(
    iterable: Iterable[T],
    *,
    desc: str,
    total: int | None = None,
) -> Iterable[T]:
    """Wrap an iterable with tqdm when available, otherwise print coarse progress."""
    try:
        from tqdm import tqdm

        return tqdm(iterable, desc=desc, total=total, unit="file")
    except Exception:
        return _print_progress(iterable, desc=desc, total=total)


def _print_progress(
    iterable: Iterable[T],
    *,
    desc: str,
    total: int | None,
) -> Iterator[T]:
    count = 0
    next_report = 0.1
    print(f"{desc}: 0/{total}" if total is not None else f"{desc}: 0")

    for item in iterable:
        yield item
        count += 1
        if total is None or total <= 0:
            if count % 10 == 0:
                print(f"{desc}: {count}")
            continue

        fraction = count / total
        if fraction >= next_report or count == total:
            print(f"{desc}: {count}/{total}")
            while fraction >= next_report:
                next_report += 0.1
