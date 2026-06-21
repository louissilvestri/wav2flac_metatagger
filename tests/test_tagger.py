"""Characterization tests for tagger.py — the most regression-prone module.

Pins the two bugs fixed during v1 development:
1. embed_metadata must MERGE tags, never delete-then-write (the audio.delete()
   bug wiped EAC metadata when MusicBrainz had gaps).
2. build_metadata_from_release must prefer the original album date
   (first_release_date) over the individual release/reissue date.
"""

from mutagen.flac import FLAC

from tagger import (embed_metadata, read_metadata, build_metadata_from_release,
                    update_raw_tags)


class TestEmbedMetadataMerge:
    def test_writes_basic_tags(self, flac_file):
        result = embed_metadata(flac_file, {"title": "Song", "artist": "Band"})
        assert result["success"]
        audio = FLAC(flac_file)
        assert audio["TITLE"] == ["Song"]
        assert audio["ARTIST"] == ["Band"]

    def test_preserves_existing_tags_not_in_new_metadata(self, flac_file):
        """REGRESSION: a second write must not delete fields it doesn't mention."""
        embed_metadata(flac_file, {
            "title": "Song", "artist": "Band",
            "genre": "Rock", "composer": "Writer", "isrc": "USRC17600001",
        })
        # Re-tag with a subset — simulates MusicBrainz data with gaps
        embed_metadata(flac_file, {"title": "New Title", "artist": "New Band"})

        audio = FLAC(flac_file)
        assert audio["TITLE"] == ["New Title"]
        assert audio["ARTIST"] == ["New Band"]
        assert audio["GENRE"] == ["Rock"], "GENRE was deleted by re-tag"
        assert audio["COMPOSER"] == ["Writer"], "COMPOSER was deleted by re-tag"
        assert audio["ISRC"] == ["USRC17600001"], "ISRC was deleted by re-tag"

    def test_empty_values_do_not_clear_existing(self, flac_file):
        embed_metadata(flac_file, {"title": "Song", "genre": "Rock"})
        embed_metadata(flac_file, {"title": "Song", "genre": ""})
        audio = FLAC(flac_file)
        assert audio["GENRE"] == ["Rock"], "empty string cleared an existing tag"

    def test_none_values_skipped(self, flac_file):
        result = embed_metadata(flac_file, {"title": "Song", "genre": None})
        assert result["success"]
        audio = FLAC(flac_file)
        assert "GENRE" not in audio


class TestUpdateRawTags:
    """The advanced tag editor: set exactly what it's told, delete on empty."""

    def test_sets_and_overwrites_arbitrary_tags(self, flac_file):
        embed_metadata(flac_file, {"title": "Song", "genre": "Rock"})
        result = update_raw_tags(flac_file, {"GENRE": "Jazz", "MOOD": "Mellow"})
        assert result["success"]
        audio = FLAC(flac_file)
        assert audio["GENRE"] == ["Jazz"]      # overwritten, not merged
        assert audio["MOOD"] == ["Mellow"]     # arbitrary new tag
        assert audio["TITLE"] == ["Song"]      # untouched tag preserved

    def test_empty_or_none_deletes_tag(self, flac_file):
        embed_metadata(flac_file, {"title": "Song", "genre": "Rock", "comment": "x"})
        update_raw_tags(flac_file, {"GENRE": "", "COMMENT": None})
        audio = FLAC(flac_file)
        assert "GENRE" not in audio
        assert "COMMENT" not in audio
        assert audio["TITLE"] == ["Song"]

    def test_key_is_case_insensitive(self, flac_file):
        embed_metadata(flac_file, {"title": "Song"})
        update_raw_tags(flac_file, {"genre": "Rock"})
        audio = FLAC(flac_file)
        assert audio["GENRE"] == ["Rock"]

class TestPublisherFanout:
    def test_label_writes_publisher_and_label_tags(self, flac_file):
        """Label fans out to ORGANIZATION/PUBLISHER/LABEL so Windows Explorer's
        Publisher field (and other players) populate."""
        result = embed_metadata(flac_file, {"label": "Fantasy Records"})
        assert result["success"]
        audio = FLAC(flac_file)
        assert audio["ORGANIZATION"] == ["Fantasy Records"]
        assert audio["PUBLISHER"] == ["Fantasy Records"]
        assert audio["LABEL"] == ["Fantasy Records"]


class TestUpdateRawTagsArt:
    def test_never_touches_cover_art(self, flac_file):
        from mutagen.flac import Picture
        audio = FLAC(flac_file)
        pic = Picture(); pic.type = 3; pic.mime = "image/jpeg"; pic.data = b"\xff\xd8\xff\xe0junk"
        audio.add_picture(pic)
        audio.save()
        update_raw_tags(flac_file, {"METADATA_BLOCK_PICTURE": "garbage", "TITLE": "Song"})
        reread = FLAC(flac_file)
        assert reread.pictures, "cover art was dropped by a raw tag edit"
        assert reread["TITLE"] == ["Song"]

    def test_multivalue_fields(self, flac_file):
        embed_metadata(flac_file, {"genre": ["Rock", "Blues"]})
        audio = FLAC(flac_file)
        assert audio["GENRE"] == ["Rock", "Blues"]

    def test_encoder_tag_always_set(self, flac_file):
        embed_metadata(flac_file, {"title": "Song"})
        audio = FLAC(flac_file)
        assert "ENCODER" in audio


class TestReadMetadata:
    def test_keys_are_uppercase(self, flac_file):
        """REGRESSION: mutagen stores keys lowercase; read_metadata must
        uppercase them (the scan-came-up-empty bug)."""
        embed_metadata(flac_file, {"title": "Song", "artist": "Band"})
        result = read_metadata(flac_file)
        assert result["success"]
        assert result["tags"]["TITLE"] == "Song"
        assert result["tags"]["ARTIST"] == "Band"

    def test_missing_file(self):
        result = read_metadata(r"C:\nonexistent\nope.flac")
        assert not result["success"]
        assert result["tags"] == {}

    def test_multivalue_returned_as_list(self, flac_file):
        embed_metadata(flac_file, {"genre": ["Rock", "Blues"]})
        result = read_metadata(flac_file)
        assert result["tags"]["GENRE"] == ["Rock", "Blues"]


class TestBuildMetadataFromRelease:
    RELEASE = {
        "id": "rel-1",
        "title": "Cosmo's Factory",
        "artist": "Creedence Clearwater Revival",
        "artist_id": "artist-1",
        "release_group_id": "rg-1",
        "genre": "Rock",
        "date": "2008-09-02",               # CD reissue date
        "first_release_date": "1970-07-08",  # original album date
        "label": "Fantasy",
        "catalog_number": "8402",
        "barcode": "025218840224",
        "discs": [{
            "position": 1,
            "format": "CD",
            "tracks": [
                {"position": 1, "title": "Ramble Tamble", "artist": "",
                 "artist_id": "", "isrc": "", "recording_id": "rec-1"},
            ],
        }],
    }

    def test_prefers_first_release_date(self):
        """REGRESSION: must use original album date, not the reissue date."""
        meta = build_metadata_from_release(self.RELEASE, 1, 1)
        assert meta["date"] == "1970-07-08"

    def test_falls_back_to_release_date(self):
        release = dict(self.RELEASE, first_release_date="")
        meta = build_metadata_from_release(release, 1, 1)
        assert meta["date"] == "2008-09-02"

    def test_track_fields(self):
        meta = build_metadata_from_release(self.RELEASE, 1, 1)
        assert meta["title"] == "Ramble Tamble"
        assert meta["album"] == "Cosmo's Factory"
        assert meta["albumartist"] == "Creedence Clearwater Revival"
        assert meta["tracknumber"] == "1"
        assert meta["tracktotal"] == "1"
        assert meta["disctotal"] == "1"
        assert meta["musicbrainz_trackid"] == "rec-1"

    def test_empty_fields_omitted(self):
        meta = build_metadata_from_release(self.RELEASE, 1, 1)
        assert all(v for v in meta.values()), "empty values must be filtered out"
