"""
analysis.py – Analyse snapshots.json produced by data_collection.py.

For three rating groups  (< 1000 | < 2000 | < 3000) this script finds:
  1. The most optimal tag distribution (tags that correlate with positive
     rating growth, ranked by mean weighted score).
  2. The optimal problem-rating range to practise.
  3. Summary statistics for each group.
"""

import json
import sys
from collections import defaultdict
from statistics import mean, stdev

# ── helpers ────────────────────────────────────────────────────────────────────

GROUPS = [
    {"name": "< 1000", "min": 0,    "max": 999},
    {"name": "< 2000", "min": 1000, "max": 1999},
    {"name": "< 3000", "min": 2000, "max": 2999},
]

SNAPSHOT_FILE = "./data/snapshots.json"

# Normalise rating-growth to a 0-1 score within each group so that groups with
# very different absolute growth values are still comparable.
def min_max_normalise(values):
    lo, hi = min(values), max(values)
    if hi == lo:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def load_snapshots(path=SNAPSHOT_FILE):
    with open(path) as f:
        raw = json.load(f)

    snapshots = []
    for s in raw:
        # Reconstruct rating_growth_class as plain value if needed
        snapshots.append(s)
    return snapshots


def group_snapshots(snapshots):
    """Bucket each snapshot by the user's rating at that point in time."""
    grouped = {g["name"]: [] for g in GROUPS}
    for s in snapshots:
        r = s.get("rating_at_t", 0)
        for g in GROUPS:
            if g["min"] <= r <= g["max"]:
                grouped[g["name"]].append(s)
                break
    return grouped


# ── tag analysis ───────────────────────────────────────────────────────────────

def analyse_tags(snapshots):
    """
    For each snapshot weight every tag by the normalised rating growth.
    Returns a dict  tag -> mean_weighted_score  sorted descending.
    """
    if not snapshots:
        return {}

    growths = [s["rating_growth"] for s in snapshots]
    norm_scores = min_max_normalise(growths)

    tag_scores = defaultdict(list)

    for snap, score in zip(snapshots, norm_scores):
        tag_ratios = snap.get("features", {}).get("accepted_tag_ratios", {})
        for tag, ratio in tag_ratios.items():
            # Weight the score by how heavily this tag was practised
            tag_scores[tag].append(score * ratio)

    result = {}
    for tag, scores in tag_scores.items():
        result[tag] = {
            "mean_weighted_score": mean(scores),
            "occurrences": len(scores),
            "std": stdev(scores) if len(scores) > 1 else 0.0,
        }

    return dict(sorted(result.items(), key=lambda x: -x[1]["mean_weighted_score"]))


# ── problem-rating analysis ────────────────────────────────────────────────────

BUCKET_ORDER = ["<=800", "<=1200", "<=1600", "<=2000", "<=2400", "<=3000", ">3000"]

def analyse_problem_ratings(snapshots):
    """
    For every rating bucket, compute the mean normalised growth of snapshots
    that had at least some presence in that bucket.  Higher value = better.
    Returns list of (bucket, mean_score) sorted descending.
    """
    if not snapshots:
        return {}

    growths = [s["rating_growth"] for s in snapshots]
    norm_scores = min_max_normalise(growths)

    bucket_scores = defaultdict(list)

    for snap, score in zip(snapshots, norm_scores):
        bucket_ratios = snap.get("features", {}).get("rating_bucket_ratios", {})
        for bucket, ratio in bucket_ratios.items():
            if ratio > 0:
                bucket_scores[bucket].append(score * ratio)

    result = {}
    for bucket in BUCKET_ORDER:
        scores = bucket_scores.get(bucket, [])
        result[bucket] = {
            "mean_weighted_score": mean(scores) if scores else 0.0,
            "occurrences": len(scores),
        }

    return dict(sorted(result.items(), key=lambda x: -x[1]["mean_weighted_score"]))


# ── summary stats ──────────────────────────────────────────────────────────────

def group_summary(snapshots):
    if not snapshots:
        return {}

    growths      = [s["rating_growth"]                        for s in snapshots]
    solve_rates  = [s["features"]["solve_rate"]               for s in snapshots if "features" in s]
    avg_ratings  = [s["features"]["avg_problem_rating"]       for s in snapshots if s.get("features", {}).get("avg_problem_rating", 0) > 0]
    avg_gaps     = [s["features"]["avg_rating_gap"]           for s in snapshots if "features" in s]

    return {
        "snapshot_count": len(snapshots),
        "mean_rating_growth":    round(mean(growths), 2),
        "mean_solve_rate":       round(mean(solve_rates), 3)   if solve_rates  else None,
        "mean_avg_problem_rating": round(mean(avg_ratings), 1) if avg_ratings  else None,
        "mean_avg_rating_gap":   round(mean(avg_gaps), 1)      if avg_gaps     else None,
    }


# ── formatting helpers ─────────────────────────────────────────────────────────

def print_section(title):
    width = 70
    print("\n" + "=" * width)
    print(f"  {title}")
    print("=" * width)


def print_group_report(group_name, snapshots):
    print_section(f"GROUP: {group_name}  ({len(snapshots)} snapshots)")

    summary = group_summary(snapshots)
    print(f"\n  Snapshots          : {summary.get('snapshot_count')}")
    print(f"  Mean rating growth : {summary.get('mean_rating_growth')}")
    print(f"  Mean solve rate    : {summary.get('mean_solve_rate')}")
    print(f"  Mean problem rating: {summary.get('mean_avg_problem_rating')}")
    print(f"  Mean rating gap    : {summary.get('mean_avg_rating_gap')}")

    # ── Tags ──────────────────────────────────────────────────────────────────
    tags = analyse_tags(snapshots)
    print(f"\n  TOP TAGS (by weighted growth score):")
    print(f"  {'Tag':<30}  {'Score':>8}  {'Count':>6}  {'Std':>6}")
    print(f"  {'-'*30}  {'-'*8}  {'-'*6}  {'-'*6}")
    for idx, (tag, info) in enumerate(tags.items()):
        if idx >= 15:
            break
        print(f"  {tag:<30}  {info['mean_weighted_score']:>8.4f}  "
              f"{info['occurrences']:>6}  {info['std']:>6.4f}")

    # ── Problem ratings ───────────────────────────────────────────────────────
    prob_ratings = analyse_problem_ratings(snapshots)
    print(f"\n  OPTIMAL PROBLEM RATING RANGE (by weighted growth score):")
    print(f"  {'Bucket':<10}  {'Score':>8}  {'Count':>6}")
    print(f"  {'-'*10}  {'-'*8}  {'-'*6}")
    for bucket, info in prob_ratings.items():
        marker = "  <-- recommended" if list(prob_ratings.keys())[0] == bucket else ""
        print(f"  {bucket:<10}  {info['mean_weighted_score']:>8.4f}  "
              f"{info['occurrences']:>6}{marker}")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    snap_path = sys.argv[1] if len(sys.argv) > 1 else SNAPSHOT_FILE

    print(f"Loading snapshots from: {snap_path}")
    snapshots = load_snapshots(snap_path)
    print(f"Total snapshots loaded: {len(snapshots)}")

    grouped = group_snapshots(snapshots)

    for g in GROUPS:
        name = g["name"]
        group_snaps = grouped[name]
        print_group_report(name, group_snaps)

    print("\n")


if __name__ == "__main__":
    main()
