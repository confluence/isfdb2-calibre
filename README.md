# isfdb2-calibre

This is a reimplementation of the ISFDB Calibre plugin, optimised for cataloguing of physical collections of speculative fiction books, and matching specific editions as closely as possible. It is based on the [ISFDB Calibre plugin][1] written by @XtinaSchelin, which I was maintaining in a [fork][2]. Calibre was migrated to Python 3 in version 5.0, and I have migrated this plugin accordingly. I will not be maintaining a Python 2 fork for older Calibre versions.

This code is mostly a personal project that got a little out of control. It's a work in progress, and is infrequently updated, but isn't dead! I still haven't completed my book catalogue, but I only remember to work on it once every couple of months. That means that sometimes changes to the ISFDB site may break the plugin until I notice. Issues and pull requests are welcome! I can't promise that I'll merge every suggestion -- I'm trying to stick to a simple core of functions that I use and am willing to maintain.

Please also feel free to fork this project and build on it. @bertholdm is maintaining a [fork][3] which has different behaviour and is more actively maintained -- it may be more suitable for general use.

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

* If there is no ISFDB ID, the plugin will behave like any other source plugin, searching for matching records using the ISBN (or a non-ISBN catalog ID), or title and author(s). Multiple records may be returned, up to a configurable maximum, and may be merged by Calibre. First publications will be searched by ISBN or other catalog ID, then publications will be searched by title and author, and finally titles will be searched by title and author.

* You can narrow down the general search results by including a publication year or month and/or a price. Because of limitations in Calibre's plugin API, these parameters must be entered as custom identifiers into the `Ids` field (see below). Unfortunately there seems to be no way for the plugin to remove these identifiers from the existing metadata (but you can do it yourself afterwards for an individual record or with the bulk edit dialog).

* If there is a cover associated with the selected publication, only this cover will be returned. If there is no such cover, the plugin will attempt to find the associated title record and fetch more covers associated with that title, up to a configurable maximum.

## Details

### Search criteria

The plugin understands the following metadata search parameters:

| Location in Calibre | Description | Location on ISFDB | Notes |
| ------------------- | ----------- | ----------------- | ----- |
| `isfdb:XXXXX` in `Ids` field | ISFDB publication ID | numeric ID in ISFDB publication page URL (`https://www.isfdb.org/cgi-bin/pl.cgi?XXXXXX`); `Publication record #` on publication page | first preference; overrides all other parameters |
| `isfdb-title:XXXXX` in `Ids` field | ISFDB title ID | numeric ID in ISFDB title page URL (`https://www.isfdb.org/cgi-bin/title.cgi?XXXXXX`); `Title record #` on title page | second preference; overrides all other parameters except publication ID |
| `isbn:XXXXX` in `Ids` field | ISBN | `ISBN` field on publication page | third preference; overrides catalog ID, author and title |
| `isfdb-catalog:XXXXX` in `Ids` field | any older non-ISBN publisher's catalog ID | `Catalog ID` field on publication page | fourth preference; overrides author and title |
| `Title` field  | title | `Publication` field on publication page or `Title` field on title page | only used if no identifiers are provided; `contains` search |
| `Author(s)` field  | author(s) | `Author` field on publication or title page | only used if no identifiers are provided; `contains` search |
| `month:YYYY-MM` in `Ids` field  | publication month | as shown in `Date` field on publication or title page | overrides year; used if no exact publication or title ID provided |
| `year:YYYY` in `Ids` field  | publication year | as shown in `Date` field on publication or title page | ignored if month provided; used if no exact publication or title ID provided |
| `price:ZZZZ` in `Ids` field (including currency symbol) | price | `Price` field on publication page | used if no exact publication or title ID provided |

### Cookies

Most of the searches that the plugin relies on are currently restricted to logged-in users on ISFDB, so the plugin needs to be able to log in as you. To enable this, you need to export your ISFDB cookies from your browser to a plain text file (e.g. in Firefox you can use the [Export Cookies add-on](https://addons.mozilla.org/en-US/firefox/addon/export-cookies-txt/)) and enter the path to this file in the plugin's configuration. You will need to export a new file whenever the cookies expire.

## Future work

In future I hope to add improved browser integration.

The messy manual process I currently use for bulk cataloguing is documented [here](http://confluence.locustforge.net/blog/posts/isfdb-calibre/).

[1]: https://github.com/XtinaSchelin/isfdb-calibre
[2]: https://github.com/confluence/isfdb-calibre
[3]: https://github.com/bertholdm/isfdb3-calibre
