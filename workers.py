import os
import taglib

def scan_single_file(filepath):
    """
    Worker task: Reads media metadata headers in-place.
    Keeps memory footprint low and avoids copying full audio stream data.
    """
    try:
        f = taglib.File(filepath)
        # Extract the first value of each tag list, stripping trailing whitespaces
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
    """
    Worker task: Directly modifies the file metadata header in place.
    Returns a tuple of (filepath, success_status) to feed the checkpoint engine.
    """
    filepath, tag_key, target_value = task
    try:
        f = taglib.File(filepath)
        f.tags[tag_key] = [target_value]
        f.save() # C++ TagLib in-place write
        return (filepath, True)
    except Exception:
        return (filepath, False)
