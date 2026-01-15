from __future__ import annotations

from typing import Iterable


def normalize_intervals(
    intervals: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    """
    Normalize [start, end) intervals by sorting and merging overlaps/adjacent.

    Examples
    --------
    >>> normalize_intervals([(5, 7), (1, 3), (3, 5), (8, 8)])
    [(1, 7)]
    """
    cleaned: list[tuple[int, int]] = [(s, e) for s, e in intervals if s < e]
    if not cleaned:
        return []

    cleaned.sort(key=lambda it: (it[0], it[1]))
    merged: list[tuple[int, int]] = [cleaned[0]]

    for start, end in cleaned[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            if end > last_end:
                merged[-1] = (last_start, end)
        else:
            merged.append((start, end))

    return merged


def intersect_intervals(
    a: Iterable[tuple[int, int]],
    b: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    """
    Intersect two [start, end) interval lists.

    Examples
    --------
    >>> intersect_intervals([(0, 10)], [(5, 12)])
    [(5, 10)]
    """
    a_norm = normalize_intervals(a)
    b_norm = normalize_intervals(b)
    if not a_norm or not b_norm:
        return []

    out: list[tuple[int, int]] = []
    i = 0
    j = 0
    while i < len(a_norm) and j < len(b_norm):
        a_start, a_end = a_norm[i]
        b_start, b_end = b_norm[j]
        start = max(a_start, b_start)
        end = min(a_end, b_end)
        if start < end:
            out.append((start, end))

        if a_end <= b_end:
            i += 1
        else:
            j += 1

    return out


def subtract_intervals(
    a: Iterable[tuple[int, int]],
    cut: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    """
    Subtract cut intervals from a using [start, end) semantics.
    """
    a_norm = normalize_intervals(a)
    cut_norm = normalize_intervals(cut)
    if not a_norm:
        return []
    if not cut_norm:
        return a_norm.copy()

    result: list[tuple[int, int]] = []
    j = 0
    for a_start, a_end in a_norm:
        while j < len(cut_norm) and cut_norm[j][1] <= a_start:
            j += 1
        cur = a_start
        k = j
        while k < len(cut_norm) and cut_norm[k][0] < a_end:
            c_start, c_end = cut_norm[k]
            if c_start > cur:
                seg_end = min(c_start, a_end)
                if cur < seg_end:
                    result.append((cur, seg_end))
            if c_end > cur:
                cur = max(cur, c_end)
            if cur >= a_end:
                break
            k += 1
        if cur < a_end:
            result.append((cur, a_end))
        j = k

    return result


def split_by_cuts(
    intervals: Iterable[tuple[int, int]],
    cuts: Iterable[int],
) -> list[tuple[int, int]]:
    """
    Split intervals by cut indices (start < cut < end only).

    Examples
    --------
    >>> split_by_cuts([(0, 10)], [3, 7])
    [(0, 3), (3, 7), (7, 10)]
    """
    norm = normalize_intervals(intervals)
    if not norm:
        return []

    cut_list = sorted({c for c in cuts})
    if not cut_list:
        return norm.copy()

    result: list[tuple[int, int]] = []
    cpos = 0
    for start, end in norm:
        while cpos < len(cut_list) and cut_list[cpos] <= start:
            cpos += 1
        cur = start
        while cpos < len(cut_list) and cut_list[cpos] < end:
            cut = cut_list[cpos]
            if cur < cut:
                result.append((cur, cut))
            cur = cut
            cpos += 1
        if cur < end:
            result.append((cur, end))

    return result
