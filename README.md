# System Design Document: Turbo QNAP Fuzzy Music Tagger

This document details the architecture, design specifications, and deployment roadmap for the **Self-Learning Fuzzy Music Tagger**. This system is engineered specifically for massive, multi-terabyte audio collections stored on QNAP NAS devices running containerized environments.

---

## 1. The Core Problem Statement

Traditional music tagging applications (such as Mp3tag or MusicBrainz Picard) fail at scale when dealing with networked or NAS-based storage due to three primary constraints:
* **Network Latency:** Modifying headers across SMB/NFS share mount points introduces immense network overhead when handling hundreds of thousands of files.
* **Disk I/O Bottlenecks:** Standard tools often rewrite entire audio files just to change a small metadata string, multiplying disk read/write cycles.
* **Rigid Deterministic Logic:** Standard automated taggers rely heavily on exact string matches, causing systems to fail or create duplicate entries when faced with common human formatting variances (e.g., typos, missing fields, or rearranged words).

### The Objective
Build a lightweight, zero-network-overhead, containerized Python/C++ tool deployed directly on the QNAP storage array bus. The engine must profile the library to establish an in-memory baseline, apply probabilistic fuzzy scoring to resolve errors, and perform blindingly fast, in-place header modifications.

---

## 2. System Requirements

### Functional Requirements
* **In-Place Metadata Updates:** The system must edit metadata headers directly without copying or rewriting the underlying audio stream data.
* **Multi-Format Support:** Natively parse and update popular lossy and lossless formats: MP3, M4A, MP4, FLAC, OGG, and WAV.
* **Library Profiling & Self-Learning:** Scan existing files to extract a lexical baseline and automatically determine master metadata standards through statistical frequency dominance.
* **Neighborhood Consensus Voting:** Track structural trends within individual storage folders to flag and repair localized metadata anomalies (e.g., single tracks missing a genre or album artist).
* **Fuzzy Consolidation Engine:** Cluster disparate spelling string variations using token-insensitive distance scores.
* **Interactive Dashboard UI:** Provide a browser-based visualization of discovered anomalies, cluster aggregations, and batch execution statuses.

### Non-Functional Requirements
* **Maximum Hardware Saturation:** Fully utilize all available CPU cores on the host QNAP NAS via multi-threaded processing.
* **Isolate Environment Footprint:** Operate inside a Docker container to prevent modifying or polluting the host QNAP QTS/QuTS operating system libraries.
* **State Preservation (Git Tracking):** The complete code layout must be manageable via Git to maintain the system's logic and rules configuration as an intellectual asset.

---

## 3. Architecture & Tech Stack
