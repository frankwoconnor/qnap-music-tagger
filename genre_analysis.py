"""
genre_analysis.py
Genre distribution analysis and interactive rationalization.
"""

import re
from collections import Counter
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import pandas as pd
from rapidfuzz import fuzz, process


@dataclass
class GenreCluster:
    master: str
    variants: List[str]
    total_count: int
    master_count: int
    accepted: bool = True


@dataclass
class GenreAnalysisReport:
    distribution: pd.DataFrame
    clusters: List[GenreCluster]
    unclustered: List[str]
    total_tracks: int
    unique_before: int
    unique_after: int
    tracks_affected: int


def extract_genre_distribution(tracks: List[Dict[str, Any]]) -> pd.DataFrame:
    """Build a DataFrame of all unique genres with counts and percentages."""
    counter = Counter()
    for t in tracks:
        g = t.get("genre", "").strip()
        if g:
            counter[g] += 1
    total = sum(counter.values())
    rows = []
    for genre, count in counter.most_common():
        rows.append({
            "genre": genre,
            "count": count,
            "percentage": round(count / total * 100, 1)
        })
    return pd.DataFrame(rows)


def _ci_token_sort(s1: str, s2: str, **kwargs) -> float:
    """Case-insensitive token sort ratio."""
    return fuzz.token_sort_ratio(s1.lower(), s2.lower())


def suggest_genre_clusters(
    genre_list: List[str],
    counts: Counter,
    threshold: int = 80
) -> Tuple[List[GenreCluster], List[str]]:
    """Fuzzy-cluster similar genre names. Returns (clusters, unclustered)."""
    unique = sorted(set(genre_list))
    processed = set()
    clusters = []

    for genre in unique:
        if genre in processed:
            continue
        matches = process.extract(
            genre, unique,
            scorer=_ci_token_sort,
            score_cutoff=threshold
        )
        variants = [m[0] for m in matches if m[0] != genre]
        if variants:
            all_items = [genre] + variants
            def _master_key(name):
                cnt = counts.get(name, 0)
                pref = 1 if (name[:1].isupper() and name[1:].islower()) else 0
                return (cnt, pref)
            master = max(all_items, key=_master_key)
            cluster_variants = [v for v in all_items if v != master]
            total = sum(counts.get(v, 0) for v in all_items)
            clusters.append(GenreCluster(
                master=master,
                variants=cluster_variants,
                total_count=total,
                master_count=counts.get(master, 0),
            ))
            for item in all_items:
                processed.add(item)
        else:
            processed.add(genre)

    unclustered = sorted(set(unique) - set(
        item for c in clusters for item in [c.master] + c.variants
    ))
    return clusters, unclustered


def build_report(
    tracks: List[Dict[str, Any]],
    threshold: int = 80
) -> GenreAnalysisReport:
    """Full genre analysis from a track list."""
    dist = extract_genre_distribution(tracks)
    if dist.empty:
        return GenreAnalysisReport(
            distribution=dist,
            clusters=[],
            unclustered=[],
            total_tracks=len(tracks),
            unique_before=0,
            unique_after=0,
            tracks_affected=0,
        )

    genre_list = dist["genre"].tolist()
    counts = Counter(dict(zip(dist["genre"], dist["count"])))
    clusters, unclustered = suggest_genre_clusters(genre_list, counts, threshold)

    # Count unique after accepted clusters
    accepted_masters = set()
    rejected_items = set()
    for c in clusters:
        if c.accepted:
            accepted_masters.add(c.master)
        else:
            rejected_items.add(c.master)
            rejected_items.update(c.variants)
    unique_after = len(accepted_masters) + len(unclustered) + len(rejected_items)

    # Tracks affected = sum of variant counts in accepted clusters
    tracks_affected = sum(
        c.total_count - c.master_count
        for c in clusters if c.accepted
    )

    return GenreAnalysisReport(
        distribution=dist,
        clusters=clusters,
        unclustered=unclustered,
        total_tracks=len(tracks),
        unique_before=len(genre_list),
        unique_after=unique_after,
        tracks_affected=tracks_affected,
    )


def compute_impact(
    dist: pd.DataFrame,
    clusters: List[GenreCluster],
    unclustered: List[str],
) -> pd.DataFrame:
    """Return a before/after DataFrame for impact charting."""
    before = dist.set_index("genre")["count"].copy()

    mapping = {}
    for c in clusters:
        if c.accepted:
            for v in c.variants:
                mapping[v] = c.master
    # unclustered genres keep their name

    after_counts: Dict[str, int] = {}
    for genre, count in before.items():
        target = mapping.get(genre, genre)
        after_counts[target] = after_counts.get(target, 0) + count

    all_keys = sorted(set(before.index.to_list()) | set(after_counts.keys()))
    rows = []
    for k in all_keys:
        rows.append({"genre": k, "before": int(before.get(k, 0)), "after": after_counts.get(k, 0)})
    return pd.DataFrame(rows)


def clusters_to_rules(clusters: List[GenreCluster]) -> List[Dict[str, Any]]:
    """Convert accepted clusters to tag_rules.yaml format."""
    rules = []
    for c in clusters:
        if not c.accepted or not c.variants:
            continue
        pattern = "|".join(re.escape(v) for v in c.variants)
        rules.append({
            "name": f"Normalize to {c.master}",
            "enabled": True,
            "condition": {
                "field": "genre",
                "pattern": f"^({pattern})$",
                "case_insensitive": True,
            },
            "value": c.master,
            "confidence": 0.9,
        })
    return rules
