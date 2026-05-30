from typing import List, Dict, Any, Optional

def generate_minimal_genre_mapping_suggestions(
    tracks: List[Dict[str, Any]],
    standardized_genres: List[str],
    predefined_minimal_genres: Optional[List[str]] = None
) -> Dict[str, str]:
    """
    Generates initial suggestions for mapping standardized genres to a minimal set.
    Leverages MusicBrainz for more intelligent suggestions.
    
    Args:
        tracks: The full list of track metadata.
        standardized_genres: A list of unique, fuzzy-clustered genre names.
        predefined_minimal_genres: An optional list of target minimal genres.
                                   If None, a default set will be used.
                                   
    Returns:
        A dictionary where keys are standardized genres and values are proposed
        minimal genres.
    """
    from .metadata_sources import MusicBrainzSource # Moved import inside function

    if predefined_minimal_genres is None:
        # Default minimal genres - these can be configured by the user later
        predefined_minimal_genres = [
            "Rock", "Pop", "Electronic", "Classical", "Jazz", "Soundtrack",
            "Hip Hop", "Folk", "World", "Blues", "Country", "Metal", "R&B", "Other"
        ]

    musicbrainz_source = MusicBrainzSource()
    
    # Map standardized genres to a representative (artist, album) for MusicBrainz lookup
    genre_to_example_track = {}
    for track in tracks:
        genre = track.get("genre", "").strip()
        artist = track.get("artist", "").strip()
        album = track.get("album", "").strip()
        if genre and artist and album and genre in standardized_genres and genre not in genre_to_example_track:
            genre_to_example_track[genre] = (artist, album)

    mapping_suggestions = {}
    for std_genre in standardized_genres:
        matched_minimal = "Other" # Default if no match
        lower_std_genre = std_genre.lower()

        # First, try simple keyword matching
        for min_genre in predefined_minimal_genres:
            if min_genre.lower() in lower_std_genre or lower_std_genre in min_genre.lower():
                matched_minimal = min_genre
                break
        
        # Special handling for common variations (override simple match if more specific)
        if "soundtrack" in lower_std_genre or "film score" in lower_std_genre:
            matched_minimal = "Soundtrack"
        elif "hip hop" in lower_std_genre or "rap" in lower_std_genre:
            matched_minimal = "Hip Hop"
        elif "r&b" in lower_std_genre or "soul" in lower_std_genre:
            matched_minimal = "R&B"
        elif "electronic" in lower_std_genre or "dance" in lower_std_genre or "techno" in lower_std_genre:
            matched_minimal = "Electronic"
        elif "country" in lower_std_genre:
            matched_minimal = "Country"
        elif "blues" in lower_std_genre:
            matched_minimal = "Blues"
        elif "metal" in lower_std_genre:
            matched_minimal = "Metal"
        elif "classical" in lower_std_genre:
            matched_minimal = "Classical"
        elif "jazz" in lower_std_genre:
            matched_minimal = "Jazz"
        elif "folk" in lower_std_genre:
            matched_minimal = "Folk"
        elif "world" in lower_std_genre:
            matched_minimal = "World"
        elif "pop" in lower_std_genre:
            matched_minimal = "Pop"
        elif "rock" in lower_std_genre:
            matched_minimal = "Rock"

        # If still "Other" or a weak match, try MusicBrainz
        if matched_minimal == "Other" and std_genre in genre_to_example_track:
            artist, album = genre_to_example_track[std_genre]
            mb_genres = musicbrainz_source.get_musicbrainz_genre_suggestions(artist, album)
            
            if mb_genres:
                # Try to map MusicBrainz genres to our predefined minimal set
                for mb_genre in mb_genres:
                    lower_mb_genre = mb_genre.lower()
                    for min_genre in predefined_minimal_genres:
                        if min_genre.lower() in lower_mb_genre or lower_mb_genre in min_genre.lower():
                            matched_minimal = min_genre
                            break
                    if matched_minimal != "Other":
                        break # Found a match from MusicBrainz
        
        mapping_suggestions[std_genre] = matched_minimal
            
    return mapping_suggestions
