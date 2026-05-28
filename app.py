import streamlit as st
import os
import json
from collections import Counter
from multiprocessing import Pool, cpu_count
from rapidfuzz import fuzz, process

# Import picklable parallel worker functions from isolated module context
from workers import scan_single_file, apply_tag_fix

# --- PROFILING ENGINE LOGIC ---

def run_library_profiling(music_dir):
    """
    Scans media directory structure using all CPU cores. Evaluates trends,
    clusters spelling variations, and uncovers localized metadata anomalies.
    """
    supported_exts = ('.mp3', '.m4a', '.mp4', '.flac', '.ogg', '.wav', 
                      '.MP3', '.M4A', '.MP4', '.FLAC', '.OGG', '.WAV')
    all_filepaths = []
    
    # Fast non-blocking path crawling
    for root, _, files in os.walk(music_dir):
        for file in files:
            if file.lower().endswith(supported_exts):
                all_filepaths.append(os.path.join(root, file))
                
    if not all_filepaths:
        return [], {}, []

    # Map file reading tasks across all QNAP host logical CPU processing cores
    with Pool(cpu_count()) as pool:
        raw_metadata = pool.map(scan_single_file, all_filepaths)
    
    # Drop failed reads
    metadata = [m for m in raw_metadata if m is not None]
    
    # Step 1: Lexical Frequency Dominance Clustering
    unique_artists = sorted(list(set(m["artist"] for m in metadata if m["artist"])))
    artist_counts = Counter(m["artist"] for m in metadata if m["artist"])
    
    fuzzy_clusters = {}
    processed_artists = set()
    
    for artist in unique_artists:
        if artist in processed_artists:
            continue
            
        # Extract matches using a token order insensitive sorting strategy
        matches = process.extract(artist, unique_artists, scorer=fuzz.token_sort_ratio, score_cutoff=85.0)
        variants = [match[0] for match in matches if match[0] != artist]
        
        if variants:
            all_cluster_items = [artist] + variants
            # Anoint the most frequent string configuration as the Master Standard
            master_spelling = max(all_cluster_items, key=lambda x: artist_counts[x])
            aliases = [v for v in all_cluster_items if v != master_spelling]
            
            if aliases:
                fuzzy_clusters[master_spelling] = aliases
            for item in all_cluster_items:
                processed_artists.add(item)
                
    # Step 2: Neighborhood Consensus Voting Analysis
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
            
            # Check if local folder consensus exceeds 75% stability threshold
            if consensus_ratio >= 0.75:
                for track in tracks:
                    if track["genre"] != dominant_genre:
                        structural_anomalies.append({
                            "path": track["path"],
                            "field": "GENRE",
                            "current": track["genre"] or "[EMPTY]",
                            "proposed": dominant_genre,
                            "reason": f"Folder Consensus ({int(consensus_ratio * 100)}% Match)"
                        })

    return metadata, fuzzy_clusters, structural_anomalies


# --- HIGH PERFORMANCE CHECKPOINT ORCHESTRATOR ---

def execute_tasks_with_checkpoint(all_tasks, log_filename):
    """
    Streams modifications directly to disk using un-ordered iterators.
    Maintains checkpoint states to guarantee immediate disaster recovery.
    """
    checkpoint_path = os.path.join("/app", log_filename)
    processed_paths = set()
    
    # Load past tracking metrics if restarting from an unexpected interruption
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, "r") as f:
            processed_paths = set(line.strip() for line in f)
            
    # Filter operations queue to unprocessed elements only
    remaining_tasks = [t for t in all_tasks if t[0] not in processed_paths]
    
    total_to_process = len(remaining_tasks)
    if total_to_process == 0:
        st.info("All tracks in this target block have already been fully written.")
        return
        
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    
    # Open non-blocking task chunk stream across system kernels
    with Pool(cpu_count()) as pool:
        batch_counter = 0
        with open(checkpoint_path, "a") as log_file:
            # imap_unordered returns items immediately upon completion without worker starvation
            for filepath, success in pool.imap_unordered(apply_tag_fix, remaining_tasks, chunksize=100):
                if success:
                    log_file.write(f"{filepath}\n")
                
                batch_counter += 1
                
                # Performance optimization: flush buffers to drive arrays every 500 records
                if batch_counter % 500 == 0 or batch_counter == total_to_process:
                    progress_bar.progress(batch_counter / total_to_process)
                    status_text.caption(f"Progress: Completed {batch_counter} / {total_to_process} tracks...")
                    log_file.flush()
                    
    # Clean up state logging tracks upon successful completion of batch run
    if os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
    st.success(f"Processing complete! Successfully transformed {total_to_process} files.")


# --- STREAMLIT UI LAYOUT ---

st.set_page_config(page_title="Turbo QNAP Music Tagger", layout="wide")
st.title("⚡ Turbo QNAP Music Tagger & Inference Engine")

# Cache application workflow data frames within current browser session context
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
    st.success(f"Profiling complete! Analyzed {len(db)} files across system storage array.")

# Render operational work panels once library state matrices are compiled
if st.session_state.db:
    tab1, tab2 = st.tabs(["Fuzzy Spelling Consolidation", "Folder Consensus Anomalies"])
    
    with tab1:
        st.header("Probabilistic Spelling Harmonization Rules")
        if not st.session_state.clusters:
            st.info("No significant artist spelling variations detected across your metadata collection base.")
        else:
            st.markdown("The engine found master variants based on **Lexical Frequency Dominance**:")
            for master, aliases in st.session_state.clusters.items():
                with st.expander(f"Master Standard: **{master}**"):
                    st.write("Fuzzy variation mappings found across library:")
                    for alias in aliases:
                        st.caption(f"↳ Clean up variant: '{alias}'")
                    
                    if st.button(f"Consolidate Variations to {master}", key=f"btn_{master}"):
                        fix_tasks = []
                        for track in st.session_state.db:
                            if track["artist"] in aliases:
                                fix_tasks.append((track["path"], "ARTIST", master))
                        
                        # Generate a unique checkpoint file for this specific artist run
                        safe_log_name = f"checkpoint_artist_{master.replace(' ', '_').replace('/', '_')}.txt"
                        execute_tasks_with_checkpoint(fix_tasks, safe_log_name)

    with tab2:
        st.header("Structural Neighborhood Outliers")
        if not st.session_state.anomalies:
            st.success("All folder directories possess uniform values. No anomalies detected.")
        else:
            st.markdown("These individual tracks deviate from the dominant trend of their directory folder path:")
            st.dataframe(st.session_state.anomalies, use_container_width=True)
            
            if st.button("Auto-Align All Neighborhood Outliers", type="secondary"):
                fix_tasks = [(a["path"], a["field"], a["proposed"]) for a in st.session_state.anomalies]
                
                # Stream corrections to local headers with consensus protection logs
                execute_tasks_with_checkpoint(fix_tasks, "checkpoint_neighborhood_anomalies.txt")
