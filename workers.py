import os
from mutagen import File
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
from mutagen.id3 import ID3NoHeaderError

# MP4 tag atoms map to standard field names
MP4_TAG_MAP = {
    '\u00a9ART': 'ARTIST',
    '\u00a9alb': 'ALBUM',
    '\u00a9gen': 'GENRE',
    '\u00a9wrt': 'COMPOSER',
    '\u00a9day': 'DATE',
    '\u00a9nam': 'TITLE',
    'aART': 'ALBUMARTIST',
    '\u00a9too': 'ENCODEDBY',
}


def _extract_tags(audio) -> dict:
    """Extract and normalize tags from a mutagen audio object."""
    tags = {}
    if isinstance(audio, EasyID3):
        for k, v in audio.items():
            tags[k.upper()] = v[0] if v else ""
    elif audio.tags:
        for k, v in audio.tags.items():
            if hasattr(v, 'text') and v.text:
                tags[k.upper()] = str(v.text[0])
            elif isinstance(v, list) and v:
                tags[k.upper()] = str(v[0])
            else:
                tags[k.upper()] = str(v) if v else ""

    # Normalize MP4 atom names to standard field names
    for atom, std in MP4_TAG_MAP.items():
        atom_upper = atom.upper()
        if atom_upper in tags and std not in tags:
            tags[std] = tags[atom_upper]
            del tags[atom_upper]

    return tags


def scan_single_file(filepath):
    """
    Worker task: Reads media metadata headers in-place using Mutagen.
    First tries EasyID3 (normalizes ID3 tags), then falls back to File().
    """
    try:
        audio = None
        try:
            audio = EasyID3(filepath)
        except ID3NoHeaderError:
            audio = File(filepath)
        except Exception:
            audio = File(filepath)

        if audio is None:
            return None

        tags = _extract_tags(audio)

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
        return None


def apply_tag_fix(task):
    """
    Worker task: Directly modifies the file metadata header in place using Mutagen.
    Returns a tuple of (filepath, success_status) to feed the checkpoint engine.
    """
    filepath, tag_key, target_value = task
    try:
        audio = None
        try:
            audio = EasyID3(filepath)
        except ID3NoHeaderError:
            audio = File(filepath)
        except Exception:
            audio = File(filepath)

        if audio is None:
            return (filepath, False)

        if isinstance(audio, EasyID3):
            audio[tag_key.lower()] = target_value
        elif audio.tags:
            audio.tags[tag_key] = [target_value]
        else:
            if isinstance(audio, MP3):
                audio.add_tags(EasyID3)
                audio[tag_key.lower()] = target_value
            else:
                return (filepath, False)

        audio.save()
        return (filepath, True)
    except Exception as e:
        return (filepath, False)