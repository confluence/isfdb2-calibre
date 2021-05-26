#!/usr/bin/env python3

import time

from queue import Queue, Empty
from threading import Thread

from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.sources.base import Source, Option
from calibre.ebooks.metadata.book.base import Metadata

from calibre_plugins.isfdb.objects import Publication, Title, PublicationsList, TitleList, TitleCovers


class ISFDB(Source):
    name = 'ISFDB'
    description = _('Downloads metadata and covers from ISFDB')
    author = 'Adrianna Pińska'
    # author = 'Michael Detambel'
    version = (3, 0, 1)
    # ToDo: Check/code Handling multiple publications:
    # http://www.isfdb.org/cgi-bin/adv_search_results.cgi?USE_1=title_title&O_1=contains&TERM_1=Schattenexperiment&C=AND&USE_2=title_title&O_2=exact&TERM_2=&USE_3=title_title&O_3=exact&TERM_3=&USE_4=title_title&O_4=exact&TERM_4=&USE_5=title_title&O_5=exact&TERM_5=&USE_6=title_title&O_6=exact&TERM_6=&USE_7=title_title&O_7=exact&TERM_7=&USE_8=title_title&O_8=exact&TERM_8=&USE_9=title_title&O_9=exact&TERM_9=&USE_10=title_title&O_10=exact&TERM_10=&ORDERBY=title_title&ACTION=query&START=0&TYPE=Title
    minimum_calibre_version = (5, 0, 0)

    can_get_multiple_covers = True
    has_html_comments = True
    supports_gzip_transfer_encoding = False
    cached_cover_url_is_reliable = True
    prefer_results_with_isbn = False
    
    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset(['title', 'authors', 'identifier:isfdb', 'identifier:isfdb-catalog', 'identifier:isfdb-title', 'identifier:isbn', 'publisher', 'pubdate', 'comments', 'tags'])

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
    

    def identify(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30):
        '''
        This method will find exactly one result if an ISFDB ID is
        present, otherwise up to the maximum searching first for the
        ISBN and then for title and author.
        '''
        matches = set()
        
        # If we have an ISFDB ID, or a title ID, we use it to construct the publication URL directly
        book_url_tuple = self.get_book_url(identifiers)
                
        if book_url_tuple:
            id_type, id_val, url = book_url_tuple
            matches.add((url, 0)) # most relevant
            
            # If we have a publication ID and a title ID, cache the title ID
            isfdb_id = identifiers.get('isfdb', None)
            title_id = identifiers.get('isfdb-title', None)
            if isfdb_id and title_id:
                self.cache_publication_id_to_title_id(isfdb_id, title_id)
        else:
            if abort.is_set():
                return

            isbn = check_isbn(identifiers.get('isbn', None))
            catalog_id = identifiers.get('isfdb-catalog', None)

            # If there's an ISBN, search by ISBN first
            # Fall back to non-ISBN catalog ID -- ISFDB uses the same field for both.
            if isbn or catalog_id:
                query = PublicationsList.url_from_isbn(isbn or catalog_id)
                stubs = PublicationsList.from_url(self.browser, query, timeout, log)
                
                for stub in stubs:
                    matches.add((stub["url"], 1))
                    if len(matches) >= self.prefs["max_results"]:
                        break

            if abort.is_set():
                return
            
            def stripped(s):
                return "".join(c.lower() for c in s if c.isalpha() or c.isspace())
                
            authors = authors or []
            title_tokens = self.get_title_tokens(title, strip_joiners=False, strip_subtitle=True)
            author_tokens = self.get_author_tokens(authors, only_first_author=True)
            title = ' '.join(title_tokens)
            author = ' '.join(author_tokens)
            
            # If we haven't reached the maximum number of results, also search by title and author
            if len(matches) < self.prefs["max_results"] and self.prefs["search_publications"]:
                query = PublicationsList.url_from_title_and_author(title, author)
                stubs = PublicationsList.from_url(self.browser, query, timeout, log)

                for stub in stubs:
                    relevance = 2
                    if stripped(stub["title"]) == stripped(title):
                        relevance = 0
                    
                    matches.add((stub["url"], relevance))
                    
                    if len(matches) >= self.prefs["max_results"]:
                        break

            if abort.is_set():
                return
                
            # If we still haven't found enough results, also search *titles* by title and author
            if len(matches) < self.prefs["max_results"] and self.prefs["search_titles"]:
                query = TitleList.url_from_title_and_author(title, author)
                stubs = TitleList.from_url(self.browser, query, timeout, log)

                for stub in stubs:
                    relevance = 2
                    if stripped(stub["title"]) == stripped(title):
                        relevance = 0
                    
                    matches.add((stub["url"], relevance))
                    
                    if len(matches) >= self.prefs["max_results"]:
                        break
        
        if abort.is_set():
            return

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
    
    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30, get_best_cover=False):
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
                mi = results[0]
                cached_url = self.get_cached_cover_url(mi.identifiers)
                title_id = mi.identifiers.get("isfdb-title")
            else:
                # Try to get all title results
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
        try:
            self.log.info('Worker parsing ISFDB url: %r' % self.url)
            
            pub = {}
            
            if Publication.is_type_of(self.url):
                self.log.info("This url is a Publication.")
                pub = Publication.from_url(self.browser, self.url, self.timeout, self.log)

                self.log.info("pub={0}",format(pub))
                
                title_id = self.plugin.cached_publication_id_to_title_id(pub["isfdb"])
                
                if not title_id and "isfdb-title" in pub:
                    title_id = pub["isfdb-title"]
                
                if not title_id:
                    self.log.info("Could not find title ID in original metadata or on publication page. Searching for title.")
                    
                    title, author, ttype = pub["title"], pub["author_string"], pub["type"]
                    query = TitleList.url_from_exact_title_author_and_type(title, author, ttype)
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

            mi = Metadata(pub["title"], pub["authors"])

            for id_name in ("isbn", "isfdb", "isfdb-catalog", "isfdb-title"):
                if id_name in pub:
                    mi.set_identifier(id_name, pub[id_name])

            for attr in ("publisher", "pubdate", "comments", "series", "series_index", "tags"):
                if attr in pub:
                    setattr(mi, attr, pub[attr])

            # TODO: we need a test which has a title but no cover
            if pub.get("cover_url"):
                self.plugin.cache_identifier_to_cover_url(pub["isfdb"], pub["cover_url"])
                mi.has_cover = True

            mi.source_relevance = self.relevance

            # TODO: do we actually want / need this?
            if pub.get("isfdb") and pub.get("isbn"):
                self.plugin.cache_isbn_to_identifier(pub["isbn"], pub["isfdb"])

            self.plugin.clean_downloaded_metadata(mi)
            self.result_queue.put(mi)
        except Exception as e:
            self.log.exception('Worker failed to fetch and parse url %r with error %r' % (self.url, e))


if __name__ == '__main__': # tests
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
            (# By ISFDB
                {'identifiers': {'isfdb': '262210'}},
                [title_test('The Silver Locusts', exact=True), authors_test(['Ray Bradbury'])]
            ),
            (# By ISBN
                {'identifiers': {'isbn': '0330020420'}},
                [title_test('All Flesh Is Grass', exact=True), authors_test(['Clifford D. Simak'])]
            ),
            (# By author and title
                {'title': 'The End of Eternity', 'authors': ['Isaac Asimov']},
                [title_test('The End of Eternity', exact=True), authors_test(['Isaac Asimov'])]
            ),

        ], fail_missing_meta=False)
