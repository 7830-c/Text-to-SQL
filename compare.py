import re
from collections import Counter
from itertools import permutations


def _norm(v):
    if isinstance(v, float):
        return round(v, 4)           # 34.5 and 34.50000001 count as equal
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="ignore")
    return v


def _rows(rows):
    return [tuple(_norm(v) for v in r) for r in rows]


def has_order_by(sql):
    return re.search(r"\border\s+by\b", sql, re.IGNORECASE) is not None


def same_result(pred_rows, gold_rows, gold_sql):
    """True if the agent's result holds the same data as the gold result."""
    if pred_rows is None or gold_rows is None:     # a query that errored is never correct
        return False
    pred, gold = _rows(pred_rows), _rows(gold_rows)
    if len(pred) != len(gold):
        return False
    if not gold:
        return True                                 # both empty
    ncols = len(gold[0])
    if len(pred[0]) != ncols:
        return False

    ordered = has_order_by(gold_sql)                # order matters only if gold sorts

    def same(a, b):
        return a == b if ordered else Counter(a) == Counter(b)

    if same(pred, gold):
        return True
    if ncols <= 6:                                  # same data, columns in another order?
        for perm in permutations(range(ncols)):
            if same([tuple(r[i] for i in perm) for r in pred], gold):
                return True
    return False


if __name__ == "__main__":
    assert same_result([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], "SELECT x FROM t")        # order ignored
    assert not same_result([(1, "a"), (2, "b")], [(2, "b"), (1, "a")], "SELECT x FROM t ORDER BY x")
    assert same_result([("a", 1)], [(1, "a")], "SELECT x FROM t")                           # columns swapped
    assert same_result([(34.50000001,)], [(34.5,)], "SELECT x FROM t")                      # float rounding
    assert not same_result(None, [(1,)], "SELECT x FROM t")                                 # error = wrong
    assert not same_result([(1,), (1,)], [(1,)], "SELECT x FROM t")                         # duplicates count
    print("compare.py: all checks passed")