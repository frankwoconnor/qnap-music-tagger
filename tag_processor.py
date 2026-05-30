"""
Tag Processor: Orchestrates multi-tier tagging system
Coordinates: Rule-based corrections → External enrichment → Fuzzy matching
"""

import logging
from enum import Enum
from typing import Dict, List, Any
from dataclasses import dataclass
from collections import Counter
from rapidfuzz import fuzz, process

from tag_rules_engine import TagRuleEngine
from metadata_sources import MetadataEnricher, MusicBrainzSource, DiscogsSource

logger = logging.getLogger(__name__)


class TagFieldType(Enum):
    """All supported tag fields"""
    ARTIST = "artist"
    ALBUM_ARTIST = "album_artist"
    ALBUM = "album"
    TITLE = "title"
    PERFORMER = "performer"
    COMPOSER = "composer"
    GENRE = "genre"
    DATE = "date"


@dataclass
class ProcessingResult:
    """Result of tag processing"""
    rule_corrections: List[Dict[str, Any]]
    enrichments: List[Dict[str, Any]]
    fuzzy_clusters: Dict[str, Dict[str, List[str]]]
    anomalies: List[Dict[str, Any]]


class MultiTierTagProcessor:
    """Three-phase tag processing: Rules → Enrichment → Fuzzy matching"""
    
    FUZZY_STRATEGIES = {
        "aggressive": {
            "threshold": 75,
            "scorer": fuzz.token_sort_ratio,
            "description": "Catches more variations, higher false positives"
        },
        "balanced": {
            "threshold": 85,
            "scorer": fuzz.token_sort_ratio,
            "description": "Default strategy, good balance"
        },
        "conservative": {
            "threshold": 92,
            "scorer": fuzz.token_sort_ratio,
            "description": "Only exact near-matches"
        },
        "exact": {
            "threshold": 100,
            "scorer": fuzz.ratio,
            "description": "Perfect matches only"
        }
    }
    
    def __init__(
        self,
        rule_engine: TagRuleEngine = None,
        metadata_enricher: MetadataEnricher = None,
        default_strategy: str = "balanced"
    ):
        self.rule_engine = rule_engine or TagRuleEngine()
        self.metadata_enricher = metadata_enricher or self._create_default_enricher()
        self.default_strategy = default_strategy
        
        if default_strategy not in self.FUZZY_STRATEGIES:
            logger.warning(f"Unknown strategy {default_strategy}, using 'balanced'")
            self.default_strategy = "balanced"
    
    @staticmethod
    def _create_default_enricher() -> MetadataEnricher:
        """Create enricher with default sources"""
        sources = [
            MusicBrainzSource(timeout=10, rate_limit=100),
            DiscogsSource(timeout=10, rate_limit=60)
        ]
        return MetadataEnricher(sources)
    
    def process_tags(
        self,
        metadata: List[Dict[str, Any]],
        strategy: str = None,
        enable_enrichment: bool = True,
        neighborhood_anomalies: bool = True
    ) -> ProcessingResult:
        """Execute three-phase tagging pipeline"""
        strategy = strategy or self.default_strategy
        
        logger.info(f"Starting tag processing with strategy: {strategy}")
        logger.info(f"Enrichment: {'enabled' if enable_enrichment else 'disabled'}")
        
        # Phase 1: Rule-based corrections
        logger.info("Phase 1: Applying deterministic rules...")
        metadata_corrected, rule_corrections = self.rule_engine.apply_rules(metadata)
        logger.info(f"  Applied {len(rule_corrections)} rule corrections")
        
        # Phase 2: External enrichment
        enrichments = []
        if enable_enrichment:
            logger.info("Phase 2: Enriching from external sources...")
            metadata_enriched = self.metadata_enricher.enrich(metadata_corrected)
            enrichments = [m.get("enrichment") for m in metadata_enriched if m.get("enrichment")]
            metadata_corrected = metadata_enriched
            logger.info(f"  Enriched {len(enrichments)} tracks")
        else:
            logger.info("Phase 2: Enrichment disabled")
        
        # Phase 3: Fuzzy clustering
        logger.info("Phase 3: Building fuzzy clusters...")
        threshold = self.FUZZY_STRATEGIES[strategy]["threshold"]
        fuzzy_clusters = self._build_all_fuzzy_clusters(metadata_corrected, threshold, strategy)
        
        # Neighborhood anomalies
        anomalies = []
        if neighborhood_anomalies:
            logger.info("Detecting neighborhood anomalies...")
            anomalies = self._detect_neighborhood_anomalies(metadata_corrected)
            logger.info(f"  Found {len(anomalies)} anomalies")
        
        return ProcessingResult(
            rule_corrections=rule_corrections,
            enrichments=enrichments,
            fuzzy_clusters=fuzzy_clusters,
            anomalies=anomalies
        )
    
    def _build_all_fuzzy_clusters(
        self,
        metadata: List[Dict[str, Any]],
        threshold: int,
        strategy: str
    ) -> Dict[str, Dict[str, List[str]]]:
        """Build fuzzy clusters for all tag fields"""
        clusters = {}
        
        for field_type in TagFieldType:
            field_name = field_type.value
            values = self._extract_field_values(metadata, field_name)
            
            if values:
                field_clusters = self._cluster_field_values(
                    list(values), threshold, strategy
                )
                if field_clusters:
                    clusters[field_name] = field_clusters
                    logger.debug(f"  {field_name}: {len(field_clusters)} clusters from {len(values)} values")
        
        return clusters
    
    def _extract_field_values(self, metadata: List[Dict[str, Any]], field_name: str) -> set:
        """Extract unique non-empty values for a field"""
        return set(
            m.get(field_name)
            for m in metadata
            if m.get(field_name) and isinstance(m.get(field_name), str) and m.get(field_name).strip()
        )
    
    def _cluster_field_values(
        self,
        values: List[str],
        threshold: int,
        strategy: str
    ) -> Dict[str, List[str]]:
        """Perform fuzzy clustering on values"""
        if not values:
            return {}
        
        clusters = {}
        processed = set()
        value_counts = Counter(values)
        sorted_values = sorted(values, key=lambda v: value_counts[v], reverse=True)
        scorer = self.FUZZY_STRATEGIES[strategy]["scorer"]
        
        for value in sorted_values:
            if value in processed:
                continue
            
            matches = process.extract(
                value,
                [v for v in values if v not in processed],
                scorer=scorer,
                score_cutoff=float(threshold)
            )
            
            variants = [m[0] for m in matches if m[0] != value]
            
            if variants:
                all_items = [value] + variants
                master = max(all_items, key=lambda x: value_counts[x])
                
                cluster = [v for v in all_items if v != master]
                if cluster:
                    clusters[master] = cluster
                    logger.debug(f"    Cluster: '{master}' <- {cluster}")
                
                for item in all_items:
                    processed.add(item)
            else:
                processed.add(value)
        
        return clusters
    
    def _detect_neighborhood_anomalies(
        self,
        metadata: List[Dict[str, Any]],
        min_tracks: int = 3,
        stability_threshold: float = 0.75
    ) -> List[Dict[str, Any]]:
        """Detect metadata inconsistencies within folders"""
        anomalies = []
        
        folder_groups: Dict[str, List[Dict]] = {}
        for track in metadata:
            folder = track.get("folder", "")
            if folder:
                folder_groups.setdefault(folder, []).append(track)
        
        voteable_fields = ["genre", "album_artist", "composer"]
        
        for folder, tracks in folder_groups.items():
            if len(tracks) < min_tracks:
                continue
            
            for field in voteable_fields:
                values = [t.get(field) for t in tracks if t.get(field)]
                
                if len(values) >= min_tracks:
                    value_counts = Counter(values)
                    most_common, count = value_counts.most_common(1)[0]
                    consensus_ratio = count / len(tracks)
                    
                    if consensus_ratio >= stability_threshold:
                        for track in tracks:
                            if track.get(field) and track.get(field) != most_common:
                                anomalies.append({
                                    "path": track.get("path", ""),
                                    "folder": folder,
                                    "field": field,
                                    "current": track.get(field),
                                    "proposed": most_common,
                                    "consensus": f"{int(consensus_ratio * 100)}%",
                                    "reason": f"Neighborhood consensus ({int(consensus_ratio * 100)}% of folder)"
                                })
        
        return anomalies
    
    def get_strategy_info(self, strategy: str = None) -> Dict[str, Any]:
        """Get information about a fuzzy matching strategy"""
        strategy = strategy or self.default_strategy
        
        if strategy not in self.FUZZY_STRATEGIES:
            return {}
        
        strat = self.FUZZY_STRATEGIES[strategy]
        return {
            "name": strategy,
            "threshold": strat["threshold"],
            "scorer": strat["scorer"].__name__,
            "description": strat["description"]
        }
    
    def list_strategies(self) -> Dict[str, Dict[str, Any]]:
        """List all available strategies"""
        return {
            name: {
                "threshold": info["threshold"],
                "description": info["description"]
            }
            for name, info in self.FUZZY_STRATEGIES.items()
        }
