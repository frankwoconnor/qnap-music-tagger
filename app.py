import streamlit as st
import os
import taglib
import json
from collections import Counter
from multiprocessing import Pool, cpu_count
from rapidfuzz import fuzz, process

# --- CORE PROCESSING PARALLEL WORKERS ---

def scan_single_file(filepath):
    """Worker task: Reads headers in-place. Zero network bloat."""
    try:
        f = taglib.File(filepath)
        tags = {k: v[0] if v else "" for k, v in f.tags.items()}
        return {
            "path": filepath,
            "folder": os.path.dirname(filepath),
            "artist": tags.get("ARTIST", "").strip(),
            "album_artist": tags.get("ALBUMARTIST", "").strip(),
            "album": tags.get("ALBUM", "").strip(),
            "genre": tags.get("GENRE", "").strip(),
            "composer": tags.get("COMPOSER", "").strip()
        }
    except Exception:
        return None

def apply_tag_fix(task):
    """Worker task: Writes headers in place using C++ TagLib core."""
    filepath, tag_key, target_value = task
    try:
        f = taglib.File(filepath)
        f.tags[tag_key] = [target_value]
        f.save()
        return True
    except Exception:
        return False

# --- PROFILING ENGINE LOGIC ---

def run_library_profiling(music_dir):
    """Discovers trends, anomalies, and spellings via your library baseline."""
    supported_exts = ('.mp3', '.m4a', '.mp4', '.flac', '.ogg', '.wav')
    all_filepaths = []
    
    for root, _, files in os.walk(music_dir):
        for file in files:
            if file.lower().endswith(supported_exts):
                all_filepaths.append(os.path.join(root, file))
                
    if not all_filepaths:
        return [], {}, []

    # Parallelize file reading over QNAP CPU hardware
    with Pool(cpu_count()) as pool:
        raw_metadata = pool.map(scan_single_file, all_filepaths)
    
    metadata = [m for m in raw_metadata if m is not None]
    
    # Analyze unique artists for fuzzy variations
    unique_artists = sorted(list(set(m["artist"] for m in metadata if m["artist"])))
    artist_counts = Counter(m["artist"] for m in metadata if m["artist"])
    
    fuzzy_clusters = {}
    processed_artists = set()
    
    for artist in unique_artists:
        if artist in processed_artists:
            continue
        # Find close spelling variations within the library baseline
        matches = process.extract(artist, unique_artists, scorer=fuzz.token_sort_ratio, score_cutoff=85.0)
        variants = [match[0] for match in matches if match[0] != artist]
        
        if variants:
            # Elect master spelling by frequency dominance
            all_cluster_items = [artist] + variants
            master_spelling = max(all_cluster_items, key=lambda x: artist_counts[x])
            aliases = [v for v in all_cluster_items if v != master_spelling]
            if aliases:
                fuzzy_clusters[master_spelling] = aliases
            for item in all_cluster_items:
                processed_artists.add(item)
                
    # Detect structural folder anomalies (Local Consensus Voting)
    folder_groups = {}
    for track in metadata:
        folder_groups.setdefault(track["folder"], []).append(track)
        
    structural_anomalies = []
    for folder, tracks in folder_groups.items():
        genres = [t["genre"] for t in tracks if t["genre"]]
        if len(genres) >= 3:
            genre_counts = Counter(genres)
            dominant_genre, dominant_count = genre_counts.most_common(1)[0]
            consensus_ratio = dominant_count / len(tracks)
            
            # Local neighborhood threshold validation
            if consensus_ratio >= 0.75:
                for track in tracks:
                    if track["genre"] != dominant_genre:
                        structural_anomalies.append({
                            "path": track["path"],
                            "field": "GENRE",
                            "current": track["genre"] or "[EMPTY]",
                            "proposed": dominant_genre,
                            "reason": f"Folder Consensus ({int(consensus_ratio*100)}% match)"
                        })

    return metadata, fuzzy_clusters, structural_anomalies

# --- STREAMLIT UI LAYOUT ---

st.set_page_config(page_title="Turbo QNAP Music Tagger", layout="wide")
st.title("⚡ Turbo QNAP Music Tagger & Inference Engine")

if "db" not in st.session_state:
    st.session_state.db = None
    st.session_state.clusters = {}
    st.session_state.anomalies = []

target_directory = st.text_input("QNAP Media Directory Path Target", "/music")

if st.button("Analyze Library & Extract Patterns", type="primary"):
    with st.spinner("Executing parallel metadata profiling pass across library..."):
        db, clusters, anomalies = run_library_profiling(target_directory)
        st.session_state.db = db
        st.session_state.clusters = clusters
        st.session_state.anomalies = anomalies
    st.success(f"Profiling complete! Tracked {len(db)} files across system.")

# Render operational panels once library state data exists
if st.session_state.db:
    tab1, tab2 = st.tabs(["Fuzzy Spelling Consolidation", "Folder Consensus Anomalies"])
    
    with tab1:
        st.header("Probabilistic Spelling Harmonization Rules")
        if not st.session_state.clusters:
            st.info("No major spelling variations detected across your metadata collection base.")
        else:
            st.markdown("The engine found master variants based on **Lexical Frequency Dominance**:")
            for master, aliases in st.session_state.clusters.items():
                with st.expander(f"Master Standard: **{master}**"):
                    st.write("Fuzzy variation mappings found:")
                    for alias in aliases:
                        st.caption(f"↳ Clean up variant: '{alias}'")
                    
                    if st.button(f"Consolidate Variations to {master}", key=f"btn_{master}"):
                        fix_tasks = []
                        for track in st.session_state.db:
                            if track["artist"] in aliases:
                                fix_tasks.append((track["path"], "ARTIST", master))
                        
                        with st.spinner("Applying updates directly into headers..."):
                            with Pool(cpu_count()) as pool:
                                pool.map(apply_tag_fix, fix_tasks)
                        st.success(f"Successfully adjusted tracks to match: {master}")

    with tab2:
        st.header("Structural Neighborhood Outliers")
        if not st.session_state.anomalies:
            st.success("All folders have matching metadata values. No outliers detected.")
        else:
            st.markdown("These files do not match the dominant trends of their surrounding folder paths:")
            st.dataframe(st.session_state.anomalies, use_container_width=True)
            
            if st.button("Auto-Align All Neighborhood Outliers", type="secondary"):
                fix_tasks = [(a["path"], a["field"], a["proposed"]) for a in st.session_state.anomalies]
                with st.spinner("Aligning outliers to neighborhood consensus values..."):
                    with Pool(cpu_count()) as pool:
                        pool.map(apply_tag_fix, fix_tasks)
                st.success("All localized anomalies have been resolved and updated on disk.")
