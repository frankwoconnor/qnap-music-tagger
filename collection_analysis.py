"""
collection_analysis.py
Tools for analyzing and deduplicating music collections,
exporting fuzzy clusters/alias suggestions to CSV for human editing,
and importing standardization rules from CSV for deterministic rule engine.
"""

import csv
import re
from collections import Counter, defaultdict
from rapidfuzz import fuzz, process
from typing import List, Dict, Any, Optional

def analyze_and_suggest_tag_rules(
    tracks: List[Dict[str, Any]],
    fields: List[str] = ["artist", "album_artist", "album", "genre", "composer"],
    folder_hint: bool = True,
    min_cluster_size: int = 2,
    genre_max: int = 15
) -> Dict[str, Any]:
    """
    Analyze a music collection for clustering and normalization suggestions.
    Returns clusters, proposed_rules, genre suggestion, and folder-level consensus for albums.
    """
    clusters = {}
    rule_suggestions = {}

    for field in fields:
        values = [t.get(field, "").strip() for t in tracks if t.get(field, "").strip()]
        counts = Counter(values)
        unique_values = sorted(list(set(values)))
        field_clusters = {}
        processed = set()
        for val in unique_values:
            if val in processed:
                continue
            matches = process.extract(
                val, unique_values, scorer=fuzz.token_sort_ratio, score_cutoff=80
            )
            variants = [m[0] for m in matches if m[0] != val]
            if variants:
                all_items = [val] + variants
                master = max(all_items, key=lambda x: counts.get(x, 0))
                group = [v for v in all_items if v != master]
                if len(group) >= min_cluster_size:
                    field_clusters[master] = group
                    for v in all_items:
                        processed.add(v)
        clusters[field] = field_clusters

        rules = []
        for master, variants in field_clusters.items():
            pattern = "|".join(re.escape(v) for v in variants)
            rules.append({
                "name": f"Normalize {master}",
                "enabled": False,
                "condition": {
                    "field": field,
                    "pattern": f"^({pattern})$",
                    "case_insensitive": True
                },
                "value": master,
                "confidence": 0.9
            })
        rule_suggestions[field] = rules

    genre_values = [t.get("genre", "").strip() for t in tracks if t.get("genre", "").strip()]
    genre_counts = Counter(genre_values)
    top_genres = [g for g, c in genre_counts.most_common(genre_max)]

    folder_album_map = defaultdict(lambda: Counter())
    if folder_hint:
        for t in tracks:
            folder, album = t.get("folder", ""), t.get("album", "")
            if folder and album:
                folder_album_map[folder][album] += 1
    folder_album_suggestion = {
        folder: max(counter.items(), key=lambda x: x[1])[0]
        for folder, counter in folder_album_map.items()
        if len(counter) >= min_cluster_size
    }

    return {
        "clusters": clusters,
        "proposed_rules": rule_suggestions,
        "genre_suggestion": top_genres,
        "folder_album_suggestion": folder_album_suggestion,
    }

def export_suggested_rules_to_csv(clusters: dict, file_path: Optional[str] = "suggested_rules.csv", return_as_string: bool = False):
    """Export rule/fuzzy clusters to a spreadsheet for easy human editing"""
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Standard Value"] + [f"Alias {i}" for i in range(1, 16)])
    for field, field_clusters in clusters.items():
        for master, variants in field_clusters.items():
            row = [master] + variants
            writer.writerow(row)
    
    if return_as_string:
        return output.getvalue()
    else:
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            f.write(output.getvalue())
        print(f"Wrote suggested rules to {file_path}")

def load_rules_from_csv(
    file_path: str,
    field: str,
    regex_prefix: str = "~"
) -> List[Dict[str, Any]]:
    """
    Import rules from spreadsheet-style CSV. Col 0 = standard, rest = aliases (regex if startswith ~). Returns rule dicts.
    """
    rules = []
    with open(file_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            canonical = row[0].strip()
            aliases = [alias.strip() for alias in row[1:] if alias.strip()]
            for alias in aliases:
                if alias.startswith(regex_prefix):
                    pattern = alias[len(regex_prefix):]
                    rules.append({
                        "name": f"Regex {alias} → {canonical}",
                        "enabled": True,
                        "condition": {"field": field, "pattern": pattern, "case_insensitive": True},
                        "value": canonical,
                        "confidence": 0.95
                    })
                else:
                    rules.append({
                        "name": f"Alias {alias} → {canonical}",
                        "enabled": True,
                        "condition": {"field": field, "pattern": f"^{re.escape(alias)}$", "case_insensitive": True},
                        "value": canonical,
                        "confidence": 0.95
                    })
    return rules

def rules_to_yaml(rules, yaml_path: str = "rules_to_import.yaml"):
    import yaml
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump({"rules": rules}, f, allow_unicode=True)
    print(f"Rules exported to {yaml_path}")

"""
USAGE INSTRUCTIONS:

# Analyze:
tracks = ... # load your tracks list (list of dicts)
results = analyze_and_suggest_tag_rules(tracks)
export_suggested_rules_to_csv(results['clusters'], "suggested_rules.csv")
# Edit CSV, then:
imported_rules = load_rules_from_csv("suggested_rules.csv", field="artist")
# Optional YAML:
rules_to_yaml(imported_rules, "artist_rules.yaml")
"""
