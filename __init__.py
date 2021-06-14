#!/usr/bin/env python3

import time

from queue import Queue, Empty
from threading import Thread

from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.sources.base import Source, Option
from calibre.ebooks.metadata.book.base import Metadata

from calibre_plugins.isfdb.objects import Publication, Title, PublicationsList, TitleList, TitleCovers


# References:
#
# The ISFDB home page: http://www.isfdb.org/cgi-bin/index.cgi
# The ISFDB wiki: http://www.isfdb.org/wiki/index.php/Main_Page
# The ISFDB database scheme: http://www.isfdb.org/wiki/index.php/Database_Schema
# The ISFDB Web API: http://www.isfdb.org/wiki/index.php/Web_API
#
## ISFDB Bibliographic Tools
# This project provides a tool for querying a local ISFDB database
# https://sourceforge.net/projects/isfdb/
# https://sourceforge.net/p/isfdb/wiki/Home/
# https://github.com/JohnSmithDev/ISFDB-Tools
# The ISFDB database is available here: http://www.isfdb.org/wiki/index.php/ISFDB_Downloads


class ISFDB(Source):
    name = 'ISFDB'
    description = _('Downloads metadata and covers from ISFDB')
    author = 'Adrianna Pińska'
    # author = 'Michael Detambel - Forked from Adrianna Pińska'
    version = (3, 0, 1)  #  Changes in forked version: see changelog

    minimum_calibre_version = (5, 0, 0)
    can_get_multiple_covers = True
    has_html_comments = True
    supports_gzip_transfer_encoding = False
    cached_cover_url_is_reliable = True
    prefer_results_with_isbn = False

    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset(['title', 'authors',
                                'series', 'series_index', 'languages',
                                'identifier:isfdb', 'identifier:isfdb-catalog', 'identifier:isfdb-title',
                                'identifier:isbn', 'identifier:dnb', 'identifier:oclc-worldcat',
                                'publisher', 'pubdate', 'comments', 'tags'])

    # Set config values
    import calibre_plugins.isfdb.config as cfg

    '''
    :param name: The name of this option. Must be a valid python identifier
    :param type_: The type of this option, one of ('number', 'string',
                    'bool', 'choices')
    :param default: The default value for this option
    :param label: A short (few words) description of this option
    :param desc: A longer description of this option
    :param choices: A dict of possible values, used only if type='choices'.
    dict is of the form {key:human readable label, ...}
    '''
    options = (
        Option(
            'max_results',
            'number',
            10,
            _('Maximum number of search results to download:'),
            _('This setting only applies to ISBN and title / author searches. Book records with a valid ISFDB publication and/or title ID will return exactly one result.'),
        ),
        Option(
            'max_covers',
            'number',
            10,
            _('Maximum number of covers to download:'),
            _('The maximum number of covers to download. This only applies to publication records with no cover. If there is a cover associated with the record, only that cover will be downloaded.')
        ),
        Option(
            'search_publications',
            'bool',
            True,
            _('Search ISFDB publications?'),
            _('This only applies to title / author searches. A record with a publication ID will always return a publication.')
        ),
        Option(
            'search_titles',
            'bool',
            True,
            _('Search ISFDB titles?'),
            _('This only applies to title / author searches. A record with a title ID and no publication ID will always return a title.')
        ),
        Option(
            'search_options',
            'choices',
            'contains',
            _('Search options'),
            _('Choose one of the options for search variants.'),
            {'is_exactly': 'is exactly', 'is_not_exactly': 'is not exactly', 'contains': 'contains',
             'does_not_contains': 'does not contain', 'starts_with': 'starts with', 'ends_with': 'ends with'}
        ),
        Option(
            'combine_series',
            'bool',
            True,
            _('Combine series and sub-series?'),
            _('Choosing this option will set the series field with series and sub-series (if any).')
        ),
    )

    def __init__(self, *args, **kwargs):
        super(ISFDB, self).__init__(*args, **kwargs)
        self._publication_id_to_title_id_cache = {}

    def cache_publication_id_to_title_id(self, isfdb_id, title_id):
        with self.cache_lock:
            self._publication_id_to_title_id_cache[isfdb_id] = title_id

    def cached_publication_id_to_title_id(self, isfdb_id):
        with self.cache_lock:
            return self._publication_id_to_title_id_cache.get(isfdb_id, None)

    def dump_caches(self):
        dump = super(ISFDB, self).dump_caches()
        with self.cache_lock:
            dump.update({
                'publication_id_to_title_id': self._publication_id_to_title_id_cache.copy(),
            })
        return dump

    def load_caches(self, dump):
        super(ISFDB, self).load_caches(dump)
        with self.cache_lock:
            self._publication_id_to_title_id_cache.update(dump['publication_id_to_title_id'])

    def get_book_url(self, identifiers):
        isfdb_id = identifiers.get('isfdb', None)
        title_id = identifiers.get('isfdb-title', None)

        if isfdb_id:
            url = Publication.url_from_id(isfdb_id)
            return ('isfdb', isfdb_id, url)

        if title_id:
            url = Title.url_from_id(title_id)
            return ('isfdb-title', title_id, url)

        return None

    def get_cached_cover_url(self, identifiers):
        isfdb_id = identifiers.get('isfdb', None)
        if isfdb_id:
            return self.cached_identifier_to_cover_url(isfdb_id)

        # If we have multiple books with the same ISBN and no ID this may reuse the same cover for multiple books
        # But we probably won't get into this situation, so let's leave this for now
        isbn = identifiers.get('isbn', None)
        if isbn:
            return self.cached_identifier_to_cover_url(self.cached_isbn_to_identifier(isbn))

        return None

    def get_author_tokens(self, authors, only_first_author=True):
        # We override this because we don't want to strip out middle initials!
        # This *just* attempts to unscramble "surname, first name".
        if only_first_author:
            authors = authors[:1]
        for au in authors:
            if "," in au:
                parts = au.split(",")
                parts = parts[1:] + parts[:1]
                au = " ".join(parts)
            for tok in au.split():
                yield tok

    # def clean_downloaded_metadata(self, mi):
    #     '''
    #     Call this method in your plugin's identify method to normalize metadata
    #     before putting the Metadata object into result_queue. You can of
    #     course, use a custom algorithm suited to your metadata source.
    #     '''
    #     docase = mi.language == 'eng'  # or mi.is_null('language')
    #     if docase and mi.title:
    #         mi.title = fixcase(mi.title)
    #         mi.authors = fixauthors(mi.authors)
    #     if mi.tags and docase:
    #         mi.tags = list(map(fixcase, mi.tags))
    #     mi.isbn = check_isbn(mi.isbn)

    def identify(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30):
        '''
        This method will find exactly one result if an ISFDB ID is
        present, otherwise up to the maximum searching first for the
        ISBN and then for title and author.
        '''

        # log.info('*** Enter ISFDB.identify().')
        # log.info('abort={0}'.format(abort))
        # log.info('title={0}'.format(title))
        # log.info('authors={0}'.format(authors))
        # log.info('identifiers={0}'.format(identifiers))

        matches = set()

        ########################################
        # 1. Search with ISFDB ID or title ID  #
        ########################################

        # If we have an ISFDB ID, or a title ID, we use it to construct the publication URL directly
        book_url_tuple = self.get_book_url(identifiers)

        if book_url_tuple:
            id_type, id_val, url = book_url_tuple
            matches.add((url, 0))  # most relevant
            # log.info('Add match: id_type={0}, id_val={1}, url={2}.'.format(id_type, id_val, url))

            # If we have a publication ID and a title ID, cache the title ID
            isfdb_id = identifiers.get('isfdb', None)
            title_id = identifiers.get('isfdb-title', None)
            # log.info('isfdb_id={0}, title_id={1}.'.format(isfdb_id, title_id))
            if isfdb_id and title_id:
                self.cache_publication_id_to_title_id(isfdb_id, title_id)
        else:
            if abort.is_set():
                log.info('Abort is set.')
                return

            isbn = check_isbn(identifiers.get('isbn', None))
            catalog_id = identifiers.get('isfdb-catalog', None)

            ########################################
            # 2. Search with ISBN                  #
            ########################################

            # If there's an ISBN, search by ISBN first
            # Fall back to non-ISBN catalog ID -- ISFDB uses the same field for both.
            if isbn or catalog_id:
                query = PublicationsList.url_from_isbn(isbn or catalog_id, log)
                stubs = PublicationsList.from_url(self.browser, query, timeout, log)

                for stub in stubs:
                    matches.add((stub["url"], 1))
                    # log.info('Add match: {0}.'.format(stub["url"]))
                    if len(matches) >= self.prefs["max_results"]:
                        break

            log.info('{0} matches with ids.'.format(len(matches)))

            if abort.is_set():
                log.info('Abort is set.')
                return

            def stripped(s):
                return "".join(c.lower() for c in s if c.isalpha() or c.isspace())

            authors = authors or []
            title_tokens = self.get_title_tokens(title, strip_joiners=False, strip_subtitle=True)
            author_tokens = self.get_author_tokens(authors, only_first_author=True)
            title = ' '.join(title_tokens)
            author = ' '.join(author_tokens)

            # Why this? (bertholdm)
            # If we haven't reached the maximum number of results, also search by title and author
            if len(matches) < self.prefs["max_results"] and self.prefs["search_publications"]:
                query = PublicationsList.url_from_title_and_author(title, author, log)
                stubs = PublicationsList.from_url(self.browser, query, timeout, log)

                # Sort stubs in ascending order by pub year
                sorted_stubs = sorted(stubs, key=lambda k: k['pub_year'])
                # log.info('sorted_stubs from PublicationsList.from_url(): {0}.'.format(sorted_stubs))

                # for stub in stubs:
                for stub in sorted_stubs:
                    # relevance = 2
                    relevance = 0
                    if stripped(stub["title"]) == stripped(title):
                        relevance = 0

                    matches.add((stub["url"], relevance))
                    # log.info('Add match: {0}.'.format(stub["url"]))

                    if len(matches) >= self.prefs["max_results"]:
                        break

            if abort.is_set():
                log.info('Abort is set.')
                return

            log.info('No id(s) given. Trying with title and author(s).')

            ########################################
            # 3. Search with title and author(s)   #
            ########################################

            # If we still haven't found enough results, also search *titles* by title and author
            if len(matches) < self.prefs["max_results"] and self.prefs["search_titles"]:
                query = TitleList.url_from_title_and_author(title, author, log)
                # log.info('query={0} '.format(query))
                stubs = TitleList.from_url(self.browser, query, timeout, log)
                # log.info('{0} stubs found with TitleList.from_url().'.format(len(stubs)))

                for stub in stubs:
                    # log.info('stub={0}'.format(stub))
                    # relevance = 2
                    relevance = 0
                    if stripped(stub["title"]) == stripped(title):
                        relevance = 0

                    matches.add((stub["url"], relevance))
                    # log.info('Add match: {0}.'.format(stub["url"]))

                    if len(matches) >= self.prefs["max_results"]:
                        break

        if abort.is_set():
            log.info('Abort is set.')
            return

        log.info('Starting workers...')

        workers = [Worker(m_url, result_queue, self.browser, log, m_rel, self, timeout) for (m_url, m_rel) in matches]

        for w in workers:
            w.start()
            # Don't send all requests at the same time
            time.sleep(0.1)

        while not abort.is_set():
            a_worker_is_alive = False
            for w in workers:
                w.join(0.2)
                if abort.is_set():
                    break
                if w.is_alive():
                    a_worker_is_alive = True
            if not a_worker_is_alive:
                break

    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30,
                       get_best_cover=False):
        urls = []

        cached_url = self.get_cached_cover_url(identifiers)
        title_id = identifiers.get("isfdb-title")

        if not cached_url and not title_id:
            log.info("Not enough information. Running identify.")
            rq = Queue()
            self.identify(log, rq, abort, title, authors, identifiers, timeout)

            if abort.is_set():
                return

            results = []

            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break

            if len(results) == 1:
                # Found a specific publication or title; try to get cached url or title
                # log.info('Found a specific publication or title; try to get cached url or title.')
                # log.info('results[0]={}'.format(results[0]))
                mi = results[0]
                cached_url = self.get_cached_cover_url(mi.identifiers)
                title_id = mi.identifiers.get("isfdb-title")
            else:
                # Try to get all title results
                # log.info('Try to get {0} title results.'.format(len(results)))
                for mi in results:
                    title_id = mi.identifiers.get("isfdb-title")
                    if title_id:
                        break

        if cached_url:
            log.info("Using cached cover URL.")
            urls.append(cached_url)

        elif title_id:
            log.info("Finding all title covers.")
            title_covers_url = TitleCovers.url_from_id(title_id)
            urls.extend(TitleCovers.from_url(self.browser, title_covers_url, timeout, log))

        else:
            # Everything is spiders
            log.error("We were unable to find any covers.")

        if abort.is_set():
            return

        self.download_multiple_covers(title, authors, urls, get_best_cover, timeout, result_queue, abort, log)


class Worker(Thread):
    '''
    Get book details from ISFDB book page in a separate thread.
    '''

    def __init__(self, url, result_queue, browser, log, relevance, plugin, timeout=20):
        Thread.__init__(self)
        self.daemon = True
        self.url = url
        self.result_queue = result_queue
        self.log = log
        self.timeout = timeout
        self.relevance = relevance
        self.plugin = plugin
        self.browser = browser.clone_browser()

    def run(self):

        # self.log.info('*** Enter Worker.run().')

        # ToDo:
        # why not this approach for search with title and/or author(s):
        # 1. search for title record(s) (ambiguous titles) and save title record info
        # 2. for each title record search all publication recorsds
        # 3. for each publication record fetch publication data and series data and merge with title data
        # 4. present the publications found in calibre gui

        try:
            self.log.info('Worker parsing ISFDB url: %r' % self.url)

            pub = {}

            if Publication.is_type_of(self.url):
                self.log.info("This url is a Publication.")
                pub = Publication.from_url(self.browser, self.url, self.timeout, self.log)
                # self.log.info("pub={0}".format(pub))
                # {'isfdb': '675613', 'title': 'Die Hypno-Sklaven', 'authors': ['Kurt Mahr'], 'author_string': 'Kurt Mahr', 'pubdate': datetime.datetime(1975, 6, 3, 2, 0), 'isfdb-catalog': 'TA199', 'publisher': 'Pabel-Moewig', 'series': 'Terra Astra', 'series_index': 199, 'type': 'CHAPBOOK', 'dnb': '1140457357', 'comments': '

                title_id = self.plugin.cached_publication_id_to_title_id(pub["isfdb"])

                if not title_id and "isfdb-title" in pub:
                    title_id = pub["isfdb-title"]

                if not title_id:
                    self.log.info(
                        "Could not find title ID in original metadata or on publication page. Searching for title.")

                    title, author, ttype = pub["title"], pub["author_string"], pub["type"]
                    query = TitleList.url_from_exact_title_author_and_type(title, author, ttype, self.log)
                    stubs = TitleList.from_url(self.browser, query, self.timeout, self.log)

                    title_ids = [Title.id_from_url(t["url"]) for t in stubs]
                else:
                    title_ids = [title_id]

                for title_id in title_ids:
                    title_url = Title.url_from_id(title_id)

                    self.log.info("Fetching additional title information from %s" % title_url)
                    tit = Title.from_url(self.browser, title_url, self.timeout, self.log)

                    if pub["isfdb"] in tit["publications"]:
                        self.log.info("This is the correct title!")
                        # Merge title and publication info, with publication info taking precedence
                        tit.update(pub)
                        pub = tit
                        break

                    self.log.info("This is not the correct title.")

                else:
                    self.log.info("We could not find a title record for this publication.")

            elif Title.is_type_of(self.url):
                self.log.info("This url is a Title.")
                pub = Title.from_url(self.browser, self.url, self.timeout, self.log)

            else:
                self.log.error("Out of cheese error! Unrecognised url!")
                return

            if not pub.get("title") or not pub.get("authors"):
                self.log.error('Insufficient metadata found for %r' % self.url)
                return

            # Put extracted metadata in queue

            # self.log.info('Put extracted metadata in queue.')
            mi = Metadata(pub["title"], pub["authors"])

            # for id_name in ("isbn", "isfdb", "isfdb-catalog", "isfdb-title"):
            # ToDo: use IDENTIFIERS_IDS
            for id_name in ("isbn", "isfdb", "isfdb-catalog", "isfdb-title", "dnb", "oclc-worldcat"):
                if id_name in pub:
                    # self.log.info('Set identifier {0}: {1}'.format(id_name, pub[id_name]))
                    mi.set_identifier(id_name, pub[id_name])

            # Fill object mi with data from metadata source

            # for attr in ("publisher", "pubdate", "comments", "series", "series_index", "tags"):
            for attr in ("publisher", "pubdate", "comments", "series", "series_index", "tags", "language"):
                if attr in pub:
                    # self.log.info('Set metadata for attribute {0}: {1}'.format(attr, pub[attr]))
                    setattr(mi, attr, pub[attr])

            # TODO: we need a test which has a title but no cover
            if pub.get("cover_url"):
                self.plugin.cache_identifier_to_cover_url(pub["isfdb"], pub["cover_url"])
                mi.has_cover = True

            mi.source_relevance = self.relevance

            # pub search gives:
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?742977.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?503917.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?443592.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?492635.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?493580.
            # Add match: http://www.isfdb.org/cgi-bin/pl.cgi?636903.
            # title search gives:
            # Add match: http://www.isfdb.org/cgi-bin/title.cgi?2639044.
            # Add match: http://www.isfdb.org/cgi-bin/title.cgi?1477793.
            # Add match: http://www.isfdb.org/cgi-bin/title.cgi?2048538.

            # With Calibre's default behavior (merge all sources with identical titles and author(s)),
            # the following titles where displayed in calibre GUI
            # stub={'title': 'Vorwort (Zur besonderen Verwendung)', 'authors': ['K. H. Scheer'], 'url': 'http://www.isfdb.org/cgi-bin/title.cgi?2639044'}
            # stub={'title': 'Zur besonderen Verwendung', 'authors': ['K. H. Scheer'], 'url': 'http://www.isfdb.org/cgi-bin/title.cgi?1477793'}
            # stub={'title': 'Zur besonderen Verwendung (excerpt)', 'authors': ['K. H. Scheer'], 'url': 'http://www.isfdb.org/cgi-bin/title.cgi?2048538'}
            # (To be honest, only stub #2 contains really a book title. Vorwort (preface) and excerpt are not what we want)
            # And all(!) pubs are crumbled in one!

            # So, if we want not to merge metadata results on title and/or author(s) as coded alin Calibre's merge_metadata_results()

            # (See https://github.com/kovidgoyal/calibre/blob/master/src/calibre/ebooks/metadata/sources/identify.py and
            # as stated in help text for check box "more than one entry per source":
            # "Normally, the metadata download system will keep only a single result per metadata source.
            # This option will cause it to keep all results returned from every metadata source. Useful if you only use
            # one or two sources and want to select individual results from them by hand.
            # Note that result with identical title/author/identifiers are still merged."
            # See also:
            # https://www.mobileread.com/forums/showthread.php?t=224546
            # http://www.mobileread.mobi/forums/showthread.php?t=336308)

            # we have to qualify the title field with distinguish patterns before we put the metadata in the request queue.

            # Avoid Calibre's default title and/or author(s) merge behavior by distinguish titles
            if 'book_variant' in pub:
                mi.title = mi.title + ' (variant #' + str(pub['book_variant']) + ')'
                # self.log.info('Set book variant to avoid merging: {0}'.format(mi.title))

            # TODO: do we actually want / need this?
            if pub.get("isfdb") and pub.get("isbn"):
                self.plugin.cache_isbn_to_identifier(pub["isbn"], pub["isfdb"])

            self.plugin.clean_downloaded_metadata(mi)
            # self.log.info('Finally formatted metadata={0}'.format(mi))
            # self.log.info(''.join([char * 20 for char in '#']))
            self.result_queue.put(mi)

        except Exception as e:
            self.log.exception('Worker failed to fetch and parse url %r with error %r' % (self.url, e))


if __name__ == '__main__':  # tests
    # To run these test use:
    # calibre-debug -e __init__.py
    from calibre import prints
    from calibre.ebooks.metadata.sources.test import (test_identify_plugin, title_test, authors_test, isbn_test)

    # Test the plugin.
    # TODO: new test cases
    # by catalog id
    # by title id
    # multiple authors
    # anthology
    # with cover
    # without cover
    test_identify_plugin(ISFDB.name,
                         [
                             (  # By ISFDB
                                 {'identifiers': {'isfdb': '262210'}},
                                 [title_test('The Silver Locusts', exact=True), authors_test(['Ray Bradbury'])]
                             ),
                             (  # By ISBN
                                 {'identifiers': {'isbn': '0330020420'}},
                                 [title_test('All Flesh Is Grass', exact=True), authors_test(['Clifford D. Simak'])]
                             ),
                             (  # By author and title
                                 {'title': 'The End of Eternity', 'authors': ['Isaac Asimov']},
                                 [title_test('The End of Eternity', exact=True), authors_test(['Isaac Asimov'])]
                             ),

                         ], fail_missing_meta=False)
