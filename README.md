# isfdb2-calibre

This is a reimplementation of the ISFDB Calibre plugin, optimised for cataloguing of physical collections of speculative fiction books. It is based on the [ISFDB Calibre plugin][1] written by Xtina Schelin, which I was maintaining in a [fork][2]. Calibre was migrated to Python 3 in version 5.0, and I have migrated this plugin accordingly. I will not be maintaining a Python 2 fork for older Calibre versions.

## Installation instructions (Linux and Mac; Windows should be similar):

    # clone the repository
    git clone https://github.com/confluence/isfdb2-calibre.git
    
    # navigate to the parent directory
    cd isfdb2-calibre
    
    # add the plugin to calibre
    calibre-customize -b isfdb2-plugin

## Features:

* If an ISFDB publication ID is present in the book record, metadata from exactly one ISFDB publication record is fetched, together with additional information from its associated title record. This allows Calibre to be used as a catalogue of specific book editions (e.g. a metadata-only catalogue of printed books). Calibre merges metadata records with the same title and author and it's impossible to disable this behaviour, so all other source plugins must be disabled if you want to use the plugin in this mode.

* Otherwise, if an ISFDB title ID is present in the book record, metadata from exactly one ISFDB *title* record is fetched. This is helpful for cataloguing short stories which were never published as standalone publications.

* If there is no ISFDB ID, the plugin will behave like any other source plugin, searching for matching records using the ISBN (or a non-ISBN catalog ID), title and author(s). Multiple records may be returned, up to a configurable maximum, and may be merged by Calibre. First publications will be searched by ISBN or other catalog ID, then publications will be searched by title and author, and finally titles will be searched by title and author. Currently a lot of similar records are merged by Calibre's automatic de-duplication. If you want to be sure of getting the right record, use one of the identifiers.

* If there is a cover associated with the selected publication, only this cover will be returned. If there is no such cover, the plugin will attempt to find the associated title record and fetch more covers associated with that title, up to a configurable maximum.

## Details:

The plugin understands the following IDs: `isbn` (ISBN), `isfdb` (ISFDB publication ID), `isfdb-title` (ISFDB title ID), `isfdb-catalog` (any older non-ISBN publisher's catalog identifier).

This code is a work in progress, but is currently in a usable state. Pull requests are welcome!

## Future work:

In future I plan to add UI features to simplify bulk entry of book records by ISFDB ID:

* Ability to enter a list of ISFDB IDs and create new book records for all of them
* Ability to extract ISFDB IDs from the currently open tabs in a running Firefox session

The messy manual process I currently use is documented [here](http://confluence.locustforge.net/blog/posts/isfdb-calibre/).

[1]: https://github.com/XtinaSchelin/isfdb-calibre
[2]: https://github.com/confluence/isfdb-calibre
