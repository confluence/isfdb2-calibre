# isfdb2-calibre

This is a reimplementation of the ISFDB Calibre plugin, optimised for cataloguing of physical collections of speculative fiction books. It is based on the [ISFDB Calibre plugin][1] written by @XtinaSchelin, which I was maintaining in a [fork][2]. Calibre was migrated to Python 3 in version 5.0, and I have migrated this plugin accordingly. I will not be maintaining a Python 2 fork for older Calibre versions.

This code is a work in progress, and is infrequently updated, but isn't dead! I still haven't completed my book catalogue, but I only remember to work on it once every couple of months. That means that sometimes changes to the ISFDB site may break the plugin until I notice. Issues and pull requests are welcome! I can't promise that I'll merge every suggestion -- I'm trying to stick to a simple core of functions that I use and am willing to maintain.

Please also feel free to fork this project and build on it. @bertholdm is maintaining a [fork][3] which has different behaviour and is more actively maintained.

## Installation instructions (Linux and Mac; Windows should be similar)

    # clone the repository
    git clone https://github.com/confluence/isfdb2-calibre.git
    
    # navigate to the parent directory
    cd isfdb2-calibre
    
    # add the plugin to calibre
    calibre-customize -b isfdb2-plugin

## Features

* If an ISFDB publication ID is present in the book record, metadata from exactly one ISFDB publication record is fetched, together with additional information from its associated title record. This allows Calibre to be used as a catalogue of specific book editions (e.g. a metadata-only catalogue of printed books). Calibre merges metadata records with the same title and author and it's impossible to disable this behaviour, so all other source plugins must be disabled if you want to use the plugin in this mode.

* Otherwise, if an ISFDB title ID is present in the book record, metadata from exactly one ISFDB *title* record is fetched. This is helpful for cataloguing short stories which were never published as standalone publications.

* If there is no ISFDB ID, the plugin will behave like any other source plugin, searching for matching records using the ISBN (or a non-ISBN catalog ID), title and author(s). Multiple records may be returned, up to a configurable maximum, and may be merged by Calibre. First publications will be searched by ISBN or other catalog ID, then publications will be searched by title and author, and finally titles will be searched by title and author. Currently a lot of similar records are merged by Calibre's automatic de-duplication. If you want to be sure of getting the right record, use one of the identifiers.

* If there is a cover associated with the selected publication, only this cover will be returned. If there is no such cover, the plugin will attempt to find the associated title record and fetch more covers associated with that title, up to a configurable maximum.

## Details

### Identifiers

The plugin understands the following IDs:

| Calibre ID name | Description | Location on ISFDB |
-----------------------------------------------------
| `isfdb` | ISFDB publication ID | Identifier in ISFDB publication page URL (`https://www.isfdb.org/cgi-bin/pl.cgi?XXXXXX`) |
| `isfdb-title` | ISFDB title ID | Identifier in ISFDB title page URL (`https://www.isfdb.org/cgi-bin/title.cgi?XXXXXX`) |
| `isbn` | ISBN | `ISBN` field on publication page |
| `isfdb-catalog` | any older non-ISBN publisher's catalog identifier | `Catalog ID` field on publication page |

### Cookies

The cover search and title ID search require the plugin to be logged in when browsing ISFDB. To enable this, you need to export your ISFDB cookies from your browser to a plain text file (e.g. in Firefox you can use the [Export Cookies add-on](https://addons.mozilla.org/en-US/firefox/addon/export-cookies-txt/)) and enter the path to this file in the plugin's configuration. You will need to export a new file whenever the cookies expire.

## Future work

In future I plan to add UI features to simplify bulk entry of book records by ISFDB ID:

* Ability to enter a list of ISFDB IDs and create new book records for all of them
* Ability to extract ISFDB IDs from the currently open tabs in a running Firefox session

The messy manual process I currently use is documented [here](http://confluence.locustforge.net/blog/posts/isfdb-calibre/).

[1]: https://github.com/XtinaSchelin/isfdb-calibre
[2]: https://github.com/confluence/isfdb-calibre
[3]: https://github.com/bertholdm/isfdb3-calibre
