"use client";

/** Manual search override: editable Artist / Album / (optional) Song fields
 * plus a Search button. Uncontrolled — seeds from the auto-derived values and
 * hands the current values back via onSearch. Used anywhere the app runs a
 * release search so the user can correct the terms instead of being stuck with
 * what was auto-detected. */

import { useState } from "react";
import { Field, Input, Button } from "@/components/ui";

export function ManualSearch({
  defaultArtist, defaultAlbum, defaultTitle = "",
  showTitle = false, pending = false, onSearch,
}: {
  defaultArtist: string;
  defaultAlbum: string;
  defaultTitle?: string;
  showTitle?: boolean;
  pending?: boolean;
  onSearch: (v: { artist: string; album: string; title: string }) => void;
}) {
  const [artist, setArtist] = useState(defaultArtist);
  const [album, setAlbum] = useState(defaultAlbum);
  const [title, setTitle] = useState(defaultTitle);

  const submit = () => onSearch({ artist: artist.trim(), album: album.trim(), title: title.trim() });

  return (
    <div className="flex items-end gap-2">
      <Field label="Album Artist" className="flex-1">
        <Input value={artist} onChange={(e) => setArtist(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && submit()} />
      </Field>
      <Field label="Album" className="flex-1">
        <Input value={album} onChange={(e) => setAlbum(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && submit()} />
      </Field>
      {showTitle && (
        <Field label="Song" className="flex-1">
          <Input value={title} onChange={(e) => setTitle(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && submit()} />
        </Field>
      )}
      <Button variant="solid" disabled={pending || (!artist && !album)} onClick={submit}>
        {pending ? "Searching…" : "Search"}
      </Button>
    </div>
  );
}
