# isfdb2-calibre

This is a reimplementation of the ISFDB Calibre plugin, optimised for cataloguing of physical collections of speculative fiction books. It is based on the [ISFDB Calibre plugin][1] written by Xtina Schelin, which I am maintaining in a [fork][2].

## Installation instructions (Linux and Mac; Windows should be similar):

    # clone the repository
    git clone https://github.com/confluence/isfdb2-calibre.git
    
    # navigate to the plugin subdirectory
    cd isfdb2-calibre/isfdb2-plugin
    
    # add the plugin to calibre
    calibre-customize -b .

## Features:

* If an ISFDB ID is present in the book record, metadata from exactly one ISFDB publication record is fetched. This allows Calibre to be used as a catalogue of specific book editions (e.g. a metadata-only catalogue of printed books). Calibre merges metadata records with the same title and author and it's impossible to disable this behaviour, so all other source plugins must be disabled if you want to use the plugin in this mode.

* If there is no ISFDB ID, the plugin will behave like any other source plugin, searching for matching records using the ISBN (or a non-ISBN catalog ID), title and author(s). Multiple records may be returned, up to a configurable maximum, and may be merged by Calibre.

* If there is a cover associated with the selected publication, only this cover will be returned. If there is no such cover, the plugin will attempt to find the ISFDB title with a title and author search and fetch more covers associated with that title, up to a configurable maximum.

## Details:

The plugin understands the following IDs: `isbn` (ISBN), `isfdb` (ISFDB publication ID), `isfdb-title` (ISFDB title ID; not yet searchable), `isfdb-catalog` (any older non-ISBN publisher's catalog identifier).

This code is a work in progress, but is currently in a usable state. Pull requests are welcome!

## Future work:

In future I plan to add UI features to simplify bulk entry of book records by ISFDB ID:

* Ability to enter a list of ISFDB IDs and create new book records for all of them
* Ability to extract ISFDB IDs from the currently open tabs in a running Firefox session

The messy manual process I currently use is documented [here](http://confluence.locustforge.net/blog/posts/isfdb-calibre/).

[1]: https://github.com/XtinaSchelin/isfdb-calibre
[2]: https://github.com/confluence/isfdb-calibre
