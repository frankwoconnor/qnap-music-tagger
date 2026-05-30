import os
from mutagen import File
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.oggvorbis import OggVorbis
from mutagen.mp4 import MP4
from mutagen.asf import ASF
from mutagen.aiff import AIFF
from mutagen.wavpack import WavPack
from mutagen.trueaudio import TrueAudio
from mutagen.monkeysaudio import MonkeysAudio
from mutagen.musepack import Musepack
from mutagen.optimfrog import OptimFROG
from mutagen.speex import Speex
from mutagen.aac import AAC
from mutagen.apev2 import APEv2File

def scan_single_file(filepath):
    """
    Worker task: Reads media metadata headers in-place using Mutagen.
    Keeps memory footprint low and avoids copying full audio stream data.
    """
    try:
        audio = File(filepath)
        if audio is None:
            return None # Mutagen couldn't determine file type

        tags = {}
        if isinstance(audio, EasyID3):
            # EasyID3 tags are already normalized to lowercase
            for k, v in audio.items():
                tags[k.upper()] = v[0] if v else ""
        else:
            # For other formats, try to get common tags
            # This part might need refinement based on actual tag structures
            # Mutagen's File object provides a generic interface
            if audio.tags:
                for k, v in audio.tags.items():
                    # Mutagen tags can be complex, try to extract a simple string
                    if hasattr(v, 'text') and v.text:
                        tags[k.upper()] = str(v.text[0])
                    elif isinstance(v, list) and v:
                        tags[k.upper()] = str(v[0])
                    else:
                        tags[k.upper()] = str(v) if v else ""
        
        return {
            "path": filepath,
            "folder": os.path.dirname(filepath),
            "artist": tags.get("ARTIST", "").strip(),
            "album_artist": tags.get("ALBUMARTIST", "").strip(),
            "album": tags.get("ALBUM", "").strip(),
            "genre": tags.get("GENRE", "").strip(),
            "composer": tags.get("COMPOSER", "").strip()
        }
    except Exception as e:
        # print(f"Error scanning {filepath}: {e}") # For debugging
        return None

def apply_tag_fix(task):
    """
    Worker task: Directly modifies the file metadata header in place using Mutagen.
    Returns a tuple of (filepath, success_status) to feed the checkpoint engine.
    """
    filepath, tag_key, target_value = task
    try:
        audio = File(filepath)
        if audio is None:
            return (filepath, False)

        # Mutagen's EasyID3 handles common tags for MP3s
        # For other formats, direct tag manipulation might be needed
        if isinstance(audio, EasyID3):
            audio[tag_key.lower()] = target_value
        elif audio.tags:
            # For other formats, try to set the tag directly
            # This might require specific tag types depending on the format
            # For simplicity, we'll try to set it as a string list
            audio.tags[tag_key] = [target_value]
        else:
            # If no tags exist, create EasyID3 tags for MP3s
            if isinstance(audio, MP3):
                audio.add_tags(EasyID3)
                audio[tag_key.lower()] = target_value
            else:
                # For other formats without existing tags, this might not work directly
                # and would require format-specific tag creation.
                # For now, we'll consider it a failure if no tags exist and it's not an MP3
                return (filepath, False)

        audio.save()
        return (filepath, True)
    except Exception as e:
        # print(f"Error applying fix to {filepath} for {tag_key}={target_value}: {e}") # For debugging
        return (filepath, False)