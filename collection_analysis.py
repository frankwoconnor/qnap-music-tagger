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
import yaml # New import
# from metadata_sources import MusicBrainzSource # Moved import inside function

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

    standardized_genres_list = sorted(list(clusters['genre'].keys())) if 'genre' in clusters else []
    # Also include any genres that didn't form a cluster but are unique
    all_unique_genres = sorted(list(set(t.get("genre", "").strip() for t in tracks if t.get("genre", "").strip())))
    for g in all_unique_genres:
        is_clustered = False
        for master, variants in clusters.get('genre', {}).items():
            if g == master or g in variants:
                is_clustered = True
                break
        if not is_clustered and g not in standardized_genres_list:
            standardized_genres_list.append(g)
    standardized_genres_list = sorted(list(set(standardized_genres_list))) # Ensure uniqueness and sort

    return {
        "clusters": clusters,
        "proposed_rules": rule_suggestions,
        "genre_suggestion": top_genres,
        "folder_album_suggestion": folder_album_suggestion,
        "standardized_genres_list": standardized_genres_list,
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
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump({"rules": rules}, f, allow_unicode=True)
    print(f"Rules exported to {yaml_path}")

def save_genre_rules_to_yaml(
    genre_standardization_rules: List[Dict[str, Any]],
    minimal_genre_mapping: Dict[str, str],
    minimal_genres_list: List[str], # New parameter for the list of minimal genres
    yaml_path: str = "tag_rules.yaml"
):
    """
    Saves genre standardization rules and minimal genre mapping to the tag_rules.yaml file.
    """
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        config = {}
    
    if 'rules' not in config:
        config['rules'] = {}
    config['rules']['genre'] = genre_standardization_rules
    
    config['genre_mapping'] = {
        'minimal_genres': minimal_genres_list,
        'standardized_to_minimal': minimal_genre_mapping
    }
    
    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, sort_keys=False)
    print(f"Genre rules and mapping saved to {yaml_path}")

def load_genre_rules_from_yaml(yaml_path: str = "tag_rules.yaml") -> Dict[str, Any]:
    """
    Loads genre standardization rules and minimal genre mapping from the tag_rules.yaml file.
    """
    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        genre_standardization_rules = config.get('rules', {}).get('genre', [])
        minimal_genre_mapping = config.get('genre_mapping', {}).get('standardized_to_minimal', {})
        minimal_genres_list = config.get('genre_mapping', {}).get('minimal_genres', [])

        return {
            "genre_standardization_rules": genre_standardization_rules,
            "minimal_genre_mapping": minimal_genre_mapping,
            "minimal_genres_list": minimal_genres_list
        }
    except FileNotFoundError:
        print(f"Warning: {yaml_path} not found. Returning empty genre rules.")
        return {
            "genre_standardization_rules": [],
            "minimal_genre_mapping": {},
            "minimal_genres_list": []
        }
    except yaml.YAMLError as e:
        print(f"Error parsing {yaml_path}: {e}")
        return {
            "genre_standardization_rules": [],
            "minimal_genre_mapping": {},
            "minimal_genres_list": []
        }

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