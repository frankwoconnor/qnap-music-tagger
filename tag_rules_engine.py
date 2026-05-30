"""
Tag Rules Engine: Phase 1 of multi-tier tagging system
Applies deterministic rules before fuzzy matching and external enrichment
"""

import re
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
import yaml
import logging

logger = logging.getLogger(__name__)


@dataclass
class TagRule:
    """Represents a single tag correction rule"""
    name: str
    enabled: bool
    condition_field: str
    pattern: str
    value: Optional[str] = None
    action: str = "replace"
    case_insensitive: bool = True
    extract_group: int = 1
    source_field: Optional[str] = None
    confidence: float = 1.0
    
    def matches(self, field_value: str) -> bool:
        """Check if rule condition matches the field value"""
        flags = re.IGNORECASE if self.case_insensitive else 0
        return bool(re.search(self.pattern, field_value, flags))
    
    def apply(self, field_value: str) -> Tuple[str, bool]:
        """Apply rule to field value, returns (new_value, was_applied)"""
        if not self.enabled or not self.matches(field_value):
            return field_value, False
        
        try:
            if self.action == "replace":
                flags = re.IGNORECASE if self.case_insensitive else 0
                result = re.sub(self.pattern, self.value or "", field_value, flags=flags)
                return result, True
            
            elif self.action == "extract_base":
                flags = re.IGNORECASE if self.case_insensitive else 0
                match = re.search(self.pattern, field_value, flags)
                if match:
                    return match.group(self.extract_group).strip(), True
                return field_value, False
            
            elif self.action == "clear":
                return "", True
            
            elif self.action == "strip_suffix":
                flags = re.IGNORECASE if self.case_insensitive else 0
                result = re.sub(self.pattern, "", field_value, flags=flags)
                return result.strip(), True
            
            else:
                logger.warning(f"Unknown action: {self.action}")
                return field_value, False
                
        except Exception as e:
            logger.error(f"Error applying rule {self.name}: {e}")
            return field_value, False


class TagRuleEngine:
    """Executes deterministic tag correction rules from YAML configuration"""
    
    def __init__(self, rules_file: str = "tag_rules.yaml"):
        """Initialize rule engine with YAML configuration"""
        self.rules_file = Path(rules_file)
        self.rules: Dict[str, List[TagRule]] = {}
        self.whitelist: Dict[str, List[str]] = {}
        self.blacklist: Dict[str, List[str]] = {}
        self.genre_mapping_rules: Dict[str, str] = {} # New instance variable
        self.minimal_genres_list: List[str] = [] # New instance variable
        self._load_rules()
    
    def _load_rules(self) -> None:
        """Load rules from YAML file"""
        try:
            if not self.rules_file.exists():
                logger.warning(f"Rules file not found: {self.rules_file}")
                return
            
            with open(self.rules_file, 'r') as f:
                config = yaml.safe_load(f)
            
            if 'rules' in config:
                for field_name, field_rules in config['rules'].items():
                    self.rules[field_name] = []
                    for rule_dict in field_rules:
                        rule = TagRule(
                            name=rule_dict['name'],
                            enabled=rule_dict.get('enabled', True),
                            condition_field=field_name,
                            pattern=rule_dict['condition'].get('pattern', ''),
                            value=rule_dict.get('value'),
                            action=rule_dict.get('action', 'replace'),
                            case_insensitive=rule_dict.get('condition', {}).get('case_insensitive', True),
                            extract_group=rule_dict.get('condition', {}).get('extract_group', 1),
                            source_field=rule_dict.get('source_field'),
                            confidence=rule_dict.get('confidence', 1.0)
                        )
                        self.rules[field_name].append(rule)
            
            if 'whitelist' in config:
                self.whitelist = config['whitelist']
            if 'blacklist' in config:
                self.blacklist = config['blacklist']
            
            if 'genre_mapping' in config:
                self.minimal_genres_list = config['genre_mapping'].get('minimal_genres', [])
                self.genre_mapping_rules = config['genre_mapping'].get('standardized_to_minimal', {})
                logger.info(f"Loaded {len(self.genre_mapping_rules)} genre mapping rules.")
            
            logger.info(f"Loaded {sum(len(r) for r in self.rules.values())} rules")
            
        except Exception as e:
            logger.error(f"Error loading rules: {e}")
    
    def apply_rules(self, metadata: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Apply all rules to metadata collection"""
        corrections = []
        
        for track in metadata:
            for field_name, field_rules in self.rules.items():
                field_value = track.get(field_name, "").strip()
                
                if not field_value:
                    continue
                
                if self._is_whitelisted(field_name, field_value):
                    continue
                
                if self._is_blacklisted(field_name, field_value):
                    track[field_name] = ""
                    corrections.append({
                        "path": track.get("path", ""),
                        "field": field_name,
                        "original": field_value,
                        "corrected": "",
                        "reason": "Blacklisted value",
                        "rule": "blacklist",
                        "confidence": 1.0
                    })
                    continue
                
                for rule in field_rules:
                    new_value, was_applied = rule.apply(field_value)
                    if was_applied and new_value != field_value:
                        corrections.append({
                            "path": track.get("path", ""),
                            "field": field_name,
                            "original": field_value,
                            "corrected": new_value,
                            "reason": f"Rule: {rule.name}",
                            "rule": rule.name,
                            "confidence": rule.confidence
                        })
                        track[field_name] = new_value
                        field_value = new_value
                        break
            
            # Apply minimal genre mapping
            genre_val = track.get("genre", "").strip()
            if genre_val:
                mapped_genre = self.genre_mapping_rules.get(genre_val)
                if mapped_genre and mapped_genre != genre_val:
                    corrections.append({
                        "path": track.get("path", ""),
                        "field": "genre",
                        "original": genre_val,
                        "corrected": mapped_genre,
                        "reason": "Minimal genre mapping",
                        "rule": "minimal_genre_map",
                        "confidence": 1.0
                    })
                    track["genre"] = mapped_genre
        
        return metadata, corrections
    
    def _is_whitelisted(self, field_name: str, value: str) -> bool:
        """Check if value is protected from correction"""
        protected_artists = self.whitelist.get('protected_artists', [])
        if field_name in ('artist', 'album_artist'):
            return value in protected_artists
        return False
    
    def _is_blacklisted(self, field_name: str, value: str) -> bool:
        """Check if value is invalid/placeholder"""
        invalid_values = self.blacklist.get('invalid_values', [])
        invalid_genres = self.blacklist.get('invalid_genres', [])
        
        if value in invalid_values:
            return True
        if field_name == 'genre' and value in invalid_genres:
            return True
        
        return False
    
    def validate_rules(self) -> List[str]:
        """Validate rule syntax"""
        errors = []
        for field_name, field_rules in self.rules.items():
            for rule in field_rules:
                try:
                    re.compile(rule.pattern)
                except re.error as e:
                    errors.append(f"{rule.name}: Invalid regex - {e}")
        return errors
    
    def get_rule_stats(self) -> Dict[str, Any]:
        """Get statistics about loaded rules"""
        total_rules = sum(len(rules) for rules in self.rules.values())
        enabled_rules = sum(
            len([r for r in rules if r.enabled])
            for rules in self.rules.values()
        )
        
        return {
            "total_rules": total_rules,
            "enabled_rules": enabled_rules,
            "rules_by_field": {field: len(rules) for field, rules in self.rules.items()},
            "whitelist_count": len(self.whitelist.get('protected_artists', [])),
            "blacklist_count": len(self.blacklist.get('invalid_values', []))
        }
