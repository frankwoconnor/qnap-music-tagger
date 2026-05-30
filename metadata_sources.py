"""
Metadata Source Integrations: Phase 2 of multi-tier tagging system
Interfaces with external music databases for enrichment and validation
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import requests
import time

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Represents a metadata match from external source"""
    source: str
    confidence: float
    data: Dict[str, Any]
    rank: int = 0


class MetadataSource(ABC):
    """Abstract base class for metadata source integrations"""
    
    def __init__(self, timeout: int = 10, rate_limit: int = 100):
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.last_request_time = 0
    
    @abstractmethod
    def search(self, artist: str, album: str, title: str) -> List[MatchResult]:
        """Search external database for metadata"""
        pass
    
    @abstractmethod
    def enrich(self, metadata: Dict[str, Any]) -> Optional[MatchResult]:
        """Enrich single metadata entry"""
        pass
    
    def _respect_rate_limit(self) -> None:
        """Enforce rate limiting"""
        min_interval = 60.0 / self.rate_limit
        elapsed = time.time() - self.last_request_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self.last_request_time = time.time()


class MusicBrainzSource(MetadataSource):
    """MusicBrainz metadata source (no API key required)"""
    
    BASE_URL = "https://musicbrainz.org/ws/2"
    
    def __init__(self, timeout: int = 10, rate_limit: int = 100):
        super().__init__(timeout, rate_limit)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "qnap-music-tagger/1.0 (https://github.com/frankwoconnor/qnap-music-tagger)"
        })
    
    def search(self, artist: str, album: str, title: str) -> List[MatchResult]:
        """Search MusicBrainz for recording"""
        if not title:
            return []
        
        try:
            self._respect_rate_limit()
            
            query_parts = [f'recording:"{title}"']
            if artist:
                query_parts.append(f'artist:"{artist}"')
            if album:
                query_parts.append(f'release:"{album}"')
            
            query = " AND ".join(query_parts)
            
            response = self.session.get(
                f"{self.BASE_URL}/recording",
                params={"query": query, "fmt": "json", "limit": 5},
                timeout=self.timeout
            )
            response.raise_for_status()
            
            results = []
            for idx, recording in enumerate(response.json().get("recordings", [])):
                match_data = {
                    "title": recording.get("title"),
                    "artist": self._extract_artist(recording),
                    "album": self._extract_album(recording),
                    "composer": self._extract_composer(recording),
                    "date": recording.get("first-release-date"),
                }
                
                confidence = self._calculate_confidence(recording, artist, album, title)
                results.append(MatchResult(
                    source="MusicBrainz",
                    confidence=confidence,
                    data=match_data,
                    rank=idx
                ))
            
            return sorted(results, key=lambda x: x.confidence, reverse=True)
            
        except Exception as e:
            logger.error(f"MusicBrainz search error: {e}")
            return []
    
    def enrich(self, metadata: Dict[str, Any]) -> Optional[MatchResult]:
        """Enrich single track metadata"""
        results = self.search(
            metadata.get("artist", ""),
            metadata.get("album", ""),
            metadata.get("title", "")
        )
        return results[0] if results and results[0].confidence > 0.8 else None
    
    def _extract_artist(self, recording: Dict) -> str:
        """Extract primary artist from recording"""
        if "artist-credit" in recording and recording["artist-credit"]:
            artists = [credit["artist"]["name"] for credit in recording["artist-credit"]]
            return " & ".join(artists[:2])
        return ""
    
    def _extract_album(self, recording: Dict) -> str:
        """Extract album from recording releases"""
        if "releases" in recording and recording["releases"]:
            return recording["releases"][0].get("title", "")
        return ""
    
    def _extract_composer(self, recording: Dict) -> str:
        """Extract composer if available"""
        if "work-relation-list" in recording:
            for relation in recording.get("work-relation-list", []):
                if relation.get("type") == "performance":
                    return relation.get("work", {}).get("composer", "")
        return ""
    
    def _calculate_confidence(self, recording: Dict, artist: str, album: str, title: str) -> float:
        """Calculate match confidence score"""
        confidence = 0.5
        
        if recording.get("title", "").lower() == title.lower():
            confidence += 0.3
        
        rec_artist = self._extract_artist(recording).lower()
        if artist.lower() in rec_artist or rec_artist in artist.lower():
            confidence += 0.2
        
        rec_album = self._extract_album(recording).lower()
        if album and album.lower() in rec_album:
            confidence += 0.1
        
        return min(confidence, 1.0)


class DiscogsSource(MetadataSource):
    """Discogs metadata source"""
    
    BASE_URL = "https://api.discogs.com"
    
    def __init__(self, token: Optional[str] = None, timeout: int = 10, rate_limit: int = 60):
        super().__init__(timeout, rate_limit)
        self.token = token
        self.session = requests.Session()
        if token:
            self.session.headers.update({
                "Authorization": f"Discogs token={token}",
                "User-Agent": "qnap-music-tagger/1.0"
            })
    
    def search(self, artist: str, album: str, title: str) -> List[MatchResult]:
        """Search Discogs database"""
        if not artist or not album:
            return []
        
        try:
            self._respect_rate_limit()
            
            response = self.session.get(
                f"{self.BASE_URL}/database/search",
                params={"q": f"{artist} {album}", "type": "release", "per_page": 5},
                timeout=self.timeout
            )
            response.raise_for_status()
            
            results = []
            for idx, release in enumerate(response.json().get("results", [])):
                match_data = {
                    "title": release.get("title"),
                    "artist": release.get("basic_information", {}).get("artists", [{}])[0].get("name"),
                    "album": release.get("title"),
                    "date": release.get("year"),
                }
                results.append(MatchResult(
                    source="Discogs",
                    confidence=0.7 if release.get("id") else 0.5,
                    data=match_data,
                    rank=idx
                ))
            
            return results
            
        except Exception as e:
            logger.error(f"Discogs search error: {e}")
            return []
    
    def enrich(self, metadata: Dict[str, Any]) -> Optional[MatchResult]:
        """Enrich single track metadata"""
        results = self.search(
            metadata.get("artist", ""),
            metadata.get("album", ""),
            metadata.get("title", "")
        )
        return results[0] if results and results[0].confidence > 0.75 else None


class MetadataEnricher:
    """Orchestrates enrichment across multiple metadata sources"""
    
    def __init__(self, sources: List[MetadataSource], confidence_thresholds: Dict[str, float] = None):
        self.sources = sorted(sources, key=lambda s: s.__class__.__name__)
        self.confidence_thresholds = confidence_thresholds or {
            "MusicBrainz": 0.85,
            "Discogs": 0.80,
            "LastFM": 0.75,
            "AcoustID": 0.95
        }
    
    def enrich(self, metadata: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrich metadata collection from multiple sources"""
        enriched = []
        
        for track in metadata:
            track_enriched = track.copy()
            
            for source in self.sources:
                try:
                    result = source.enrich(track)
                    
                    if result:
                        threshold = self.confidence_thresholds.get(result.source, 0.8)
                        
                        if result.confidence >= threshold:
                            track_enriched["enrichment"] = {
                                "source": result.source,
                                "confidence": result.confidence,
                                "data": result.data
                            }
                            logger.debug(f"Enriched via {result.source} (confidence: {result.confidence:.2f})")
                            break
                
                except Exception as e:
                    logger.warning(f"Error enriching via {source.__class__.__name__}: {e}")
                    continue
            
            enriched.append(track_enriched)
        
        return enriched
