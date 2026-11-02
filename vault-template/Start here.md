# How this archive works

My private record of films, art, gigs, books, places, music and writing. **Nothing here is public unless its `public` box is ticked.**

## Adding an entry

1. Make a new note in the right folder (`films`, `art`, `gigs`, `books`, `places`, `music` or `writing`), named after the thing.
2. Run **Insert template** and pick the matching one (Film, Art, Gig, Book, Place, Album, Post).
3. Fill in what you know. Leave the rest blank.

Dates can be partial: `2019` or `2019-05` if that's all you remember. A second viewing or visit goes in `dates`.

## Publishing

- Tick **public** and the entry appears in the feed on wilde.page the next time the site is published (`uv run hw.py deploy`).
- Anything between `%%` markers stays private, even on a public note:

  `%% only I can see this %%`

- **with** (and **address** for places) never leave this vault, public or not.
- **Images:** fill in **image**, with any credit in **caption**, and the image appears on the entry's page. Paste the web address of an image online, which keeps loading from that site, or attach your own photo to the note (Obsidian saves it in the vault) and put its file name. Your own photos are resized for the public site, with their location data removed. Photos inside `%%` markers stay private.

## Lists

`status: want` on a book or place keeps it out of the feed: it's a want-to list. `status: reading` works the same way for books.

**Library.base** has a table for each collection, plus one for everything public and one for want-to lists.
