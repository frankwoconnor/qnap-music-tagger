import streamlit as st
import os
import json
from collections import Counter
from multiprocessing import Pool, cpu_count
from rapidfuzz import fuzz, process
import pandas as pd # New import for data_editor

# Import picklable parallel worker functions from isolated module context
from workers import scan_single_file, apply_tag_fix
from collection_analysis import (
    analyze_and_suggest_tag_rules,
    export_suggested_rules_to_csv,
    load_rules_from_csv,
    rules_to_yaml,
    generate_minimal_genre_mapping_suggestions,
    save_genre_rules_to_yaml,
    load_genre_rules_from_yaml,
)
from genre_analysis import build_report, compute_impact, clusters_to_rules

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
    checkpoint_path = os.path.join(os.path.dirname(__file__), log_filename)
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
    st.session_state.suggested_rules = None
    st.session_state.minimal_genre_mapping = {}
    st.session_state.genre_standardization_rules = []
    st.session_state.predefined_minimal_genres = []
    st.session_state.genre_report = None

    # Load genre rules and mapping on startup
    loaded_rules = load_genre_rules_from_yaml()
    st.session_state.genre_standardization_rules = loaded_rules["genre_standardization_rules"]
    st.session_state.minimal_genre_mapping = loaded_rules["minimal_genre_mapping"]
    st.session_state.predefined_minimal_genres = loaded_rules["minimal_genres_list"]

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
    tab1, tab2, tab3, tab4 = st.tabs([
        "Fuzzy Spelling Consolidation",
        "Folder Consensus Anomalies",
        "Rule Management",
        "Genre Analysis & Rationalization",
    ])
    
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

    with tab3:
        st.header("Rule Management & Advanced Analysis")
        
        # Button to generate rule suggestions
        if st.button("Generate Rule Suggestions from Collection"):
            if st.session_state.db:
                with st.spinner("Analyzing collection for rule suggestions..."):
                    analysis_results = analyze_and_suggest_tag_rules(st.session_state.db)
                    st.session_state.suggested_rules = analysis_results
                    st.session_state.genre_standardization_rules = analysis_results["proposed_rules"].get("genre", [])
                    
                    # Generate minimal genre mapping suggestions
                    standardized_genres = analysis_results.get("standardized_genres_list", [])
                    st.session_state.minimal_genre_mapping = generate_minimal_genre_mapping_suggestions(
                        st.session_state.db, # Pass tracks to the function
                        standardized_genres,
                        st.session_state.predefined_minimal_genres # Pass current minimal genres
                    )
                st.success("Rule suggestions generated!")
            else:
                st.warning("Please analyze the library first to generate rule suggestions.")
        
        if st.session_state.suggested_rules:
            st.subheader("Proposed Rules for Other Fields")
            for field, rules in st.session_state.suggested_rules["proposed_rules"].items():
                if rules and field != "genre": # Exclude genre, as it will have its own section
                    st.markdown(f"**{field.capitalize()} Rules:**")
                    for rule in rules:
                        st.json(rule)
            
            st.subheader("Genre Standardization Rules")
            if st.session_state.genre_standardization_rules:
                # Convert rules to a DataFrame for st.data_editor
                genre_rules_df = pd.DataFrame([
                    {"Original Pattern": rule["condition"]["pattern"], "Target Genre": rule["value"], "Enabled": rule["enabled"]}
                    for rule in st.session_state.genre_standardization_rules
                ])
                edited_genre_rules_df = st.data_editor(
                    genre_rules_df, 
                    num_rows="dynamic", 
                    use_container_width=True,
                    column_config={
                        "Original Pattern": st.column_config.TextColumn("Original Pattern", help="Regex pattern for original genre names"),
                        "Target Genre": st.column_config.TextColumn("Target Genre", help="Standardized genre name"),
                        "Enabled": st.column_config.CheckboxColumn("Enabled", help="Enable or disable this rule")
                    }
                )
                # Update session state with edited rules
                st.session_state.genre_standardization_rules = [
                    {
                        "name": f"Normalize {row['Target Genre']}",
                        "enabled": row["Enabled"],
                        "condition": {"field": "genre", "pattern": row["Original Pattern"], "case_insensitive": True},
                        "value": row["Target Genre"],
                        "confidence": 0.9
                    } for index, row in edited_genre_rules_df.iterrows()
                ]
            else:
                st.info("No genre standardization rules suggested.")

            st.subheader("Minimal Genre Set Mapping")
            if st.session_state.minimal_genre_mapping:
                # Allow user to define minimal genres
                default_minimal_genres_options = ["Rock", "Pop", "Electronic", "Classical", "Jazz", "Soundtrack",
                                          "Hip Hop", "Folk", "World", "Blues", "Country", "Metal", "R&B", "Other"]
                
                # Ensure all current mapped values are in the default options for multiselect
                current_mapped_values_from_mapping = list(set(st.session_state.minimal_genre_mapping.values()))
                all_minimal_options = sorted(list(set(default_minimal_genres_options + current_mapped_values_from_mapping + st.session_state.predefined_minimal_genres)))

                st.session_state.predefined_minimal_genres = st.multiselect(
                    "Define your target minimal genres (5-10 recommended):",
                    options=all_minimal_options,
                    default=st.session_state.predefined_minimal_genres,
                    key="minimal_genre_selector" # Added a key to prevent re-rendering issues
                )
                
                # Create a DataFrame for editing the mapping
                mapping_data = []
                for std_genre, min_genre in st.session_state.minimal_genre_mapping.items():
                    mapping_data.append({"Standardized Genre": std_genre, "Mapped To": min_genre})
                
                mapping_df = pd.DataFrame(mapping_data)
                
                # Use st.data_editor with a selectbox for "Mapped To" column
                edited_mapping_df = st.data_editor(
                    mapping_df,
                    column_config={
                        "Mapped To": st.column_config.SelectboxColumn(
                            "Mapped To",
                            options=st.session_state.predefined_minimal_genres, # Use user-defined minimal genres
                            required=True,
                        )
                    },
                    num_rows="fixed",
                    use_container_width=True,
                    key="minimal_genre_mapper" # Added a key
                )
                # Update session state with edited mapping
                st.session_state.minimal_genre_mapping = {
                    row["Standardized Genre"]: row["Mapped To"]
                    for index, row in edited_mapping_df.iterrows()
                }
            else:
                st.info("No minimal genre mapping suggestions.")
            
            # Save Genre Rules Button
            if st.button("Save Genre Rules to tag_rules.yaml"):
                save_genre_rules_to_yaml(
                    st.session_state.genre_standardization_rules,
                    st.session_state.minimal_genre_mapping,
                    st.session_state.predefined_minimal_genres
                )
                st.success("Genre rules and mapping saved!")

            st.download_button(
                label="Export Suggested Rules to CSV",
                data=export_suggested_rules_to_csv(st.session_state.suggested_rules["clusters"], return_as_string=True),
                file_name="suggested_rules.csv",
                mime="text/csv",
            )

    with tab4:
        st.header("Genre Analysis & Rationalization")

        if st.button("Run Genre Analysis", type="primary"):
            report = build_report(st.session_state.db)
            st.session_state.genre_report = report

        if st.session_state.genre_report:
            report = st.session_state.genre_report

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Tracks", report.total_tracks)
            col2.metric("Unique Genres Found", report.unique_before)
            col3.metric("After Rationalization", report.unique_after)
            col4.metric("Tracks to Remap", report.tracks_affected)

            st.subheader("Current Genre Distribution")
            dist_chart = report.distribution.set_index("genre")
            st.bar_chart(dist_chart["count"])
            with st.expander("View full table"):
                st.dataframe(report.distribution, use_container_width=True)

            if report.clusters:
                st.subheader("Proposed Genre Clusters")
                st.markdown("Toggle **Accept** to merge a cluster. Edit **Master Genre** to rename the target.")

                cluster_data = []
                for c in report.clusters:
                    cluster_data.append({
                        "Accept": c.accepted,
                        "Master Genre": c.master,
                        "Variants": ", ".join(c.variants),
                        "Variant Count": len(c.variants),
                        "Total Tracks": c.total_count,
                    })
                cluster_df = pd.DataFrame(cluster_data)

                edited = st.data_editor(
                    cluster_df,
                    column_config={
                        "Accept": st.column_config.CheckboxColumn("Accept", help="Merge variants into master"),
                        "Master Genre": st.column_config.TextColumn("Master Genre", help="Target genre name", required=True),
                        "Variants": st.column_config.TextColumn("Variants", disabled=True),
                        "Variant Count": st.column_config.NumberColumn("Variants", disabled=True),
                        "Total Tracks": st.column_config.NumberColumn("Tracks", disabled=True),
                    },
                    num_rows="fixed",
                    use_container_width=True,
                    key="genre_clusters_editor",
                )

                for i, row in edited.iterrows():
                    if i < len(report.clusters):
                        report.clusters[i].accepted = row["Accept"]
                        report.clusters[i].master = str(row["Master Genre"]).strip()

            if report.unclustered:
                with st.expander(f"Unclustered Genres ({len(report.unclustered)})"):
                    st.write(", ".join(report.unclustered))

            st.subheader("Impact Preview")
            impact_df = compute_impact(report.distribution, report.clusters, report.unclustered)
            impact_chart = impact_df.set_index("genre")
            st.bar_chart(impact_chart[["before", "after"]])
            with st.expander("View impact table"):
                st.dataframe(impact_df, use_container_width=True)

            rules = clusters_to_rules(report.clusters)
            if rules:
                if st.button("Save Genre Rationalization Rules to YAML"):
                    existing = load_genre_rules_from_yaml()
                    save_genre_rules_to_yaml(
                        rules,
                        existing["minimal_genre_mapping"],
                        existing["minimal_genres_list"],
                    )
                    st.success(f"Saved {len(rules)} genre rationalization rules!")
            else:
                st.info("No accepted clusters with variants to save.")
        else:
            st.info("Analyze your library first, then click **Run Genre Analysis**.")