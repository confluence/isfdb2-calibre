#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '''(c) 2017 Adrianna Pińska <adrianna.pinska@gmail.com>,
Xtina Schelin <xtina.schelin@gmail.com>,
Grant Drake <grant.drake@gmail.com>'''
__docformat__ = 'restructuredtext en'

import time
from urllib import quote, urlencode
from Queue import Queue, Empty

from lxml.html import fromstring

from calibre import as_unicode
from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.sources.base import Source
from calibre.utils.icu import lower
from calibre.utils.cleantext import clean_ascii_chars
from calibre.utils.localization import get_udc

import calibre_plugins.isfdb2.config as cfg
MAX_RESULTS = cfg.plugin_prefs[cfg.STORE_NAME][cfg.KEY_MAX_DOWNLOADS]

class ISFDB2(Source):
    name = 'ISFDB2'
    description = _('Downloads metadata and covers from ISFDB')
    author = 'Adrianna Pińska'
    version = (1, 0, 0)
    minimum_calibre_version = (0, 8, 0)

    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset(['title', 'authors', 'identifier:isfdb', 'identifier:isbn', 'publisher', 'pubdate', 'comments'])
    has_html_comments = True
    supports_gzip_transfer_encoding = False
    cached_cover_url_is_reliable = True

    SEARCH_URL = 'http://www.isfdb.org/cgi-bin/se.cgi?%s'
    ADV_SEARCH_URL = 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?%s'
    ID_URL = 'http://www.isfdb.org/cgi-bin/pl.cgi?%s'

    def config_widget(self):
        '''
        Overriding the default configuration screen for our own custom configuration
        '''
        from calibre_plugins.isfdb2.config import ConfigWidget
        return ConfigWidget(self)

    def get_book_url(self, identifiers):
        isfdb_id = identifiers.get('isfdb', None)
        if isfdb_id:
            url = self.ID_URL % isfdb_id
            return ('isfdb', isfdb_id, url)

    def create_query(self, log, title=None, authors=None, identifiers={}):
        # ISFDB ID takes precedence over everything
        isfdb_id = identifiers.get('isfdb', None)
        if isfdb_id:
            return self.get_book_url(identifiers)

        # ISBN takes precedence over title and author
        isbn = check_isbn(identifiers.get('isbn', None))
        if isbn:
            return self.SEARCH_URL % urlencode({"type": "ISBN", "arg": isbn})

        # Otherwise construct a search query from the title and author
        if title:
            title = title.replace('?', '')
            title_tokens = self.get_title_tokens(title, strip_joiners=False, strip_subtitle=True)
            # TODO is there a cleaner way to do this?
            title_tokens = [quote(t.encode('utf-8') if isinstance(t, unicode) else t) for t in title_tokens]
            search_title = '+'.join(title_tokens)
            
        if authors:
            author_tokens = self.get_author_tokens(authors, only_first_author=True)
            # TODO is there a cleaner way to do this?
            author_tokens = [quote(t.encode('utf-8') if isinstance(t, unicode) else t) for t in author_tokens]
            search_author = '+'.join(author_tokens)
        
        if not search_title and not search_author:
            return None

        field = 0
        query = {}

        if search_title and search_author:
            query.update({"CONJUNCTION_1": "AND"})

        if search_title:
            field += 1
            
            query.update({
                "USE_%d" % field: "pub_title",
                "OPERATOR_%d" % field: "contains",
                "TERM_%d" % field: search_title,
            })

        if search_author:
            field += 1
            
            query.update({
                "USE_%d" % field: "author_canonical",
                "OPERATOR_%d" % field: "contains",
                "TERM_%d" % field: search_author,
            })

        query.update({
            "ORDERBY": "pub_title",
            "START": "0",
            "TYPE": "Publication",
        })

        return self.ADV_SEARCH_URL % urlencode(query)
            
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

    def identify(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30):
        '''
        This method will find exactly one result if an ISFDB ID is
        present, otherwise up to the maximum searching first for the
        ISBN and then for title and author.
        '''
        matches = set()
        relevance = {}
        br = self.browser

        # If we have an ISFDB ID, we use it to construct the publication URL directly
        
        isfdb_id = identifiers.get('isfdb', None)
        if isfdb_id:
            url = self.get_book_url(identifiers)
            matches.add(url)
            relevance[url] = 0 # most relevant
        else:

            def html_from_url(url):
                response = br.open_novisit(url, timeout=timeout)
                raw = response.read().decode('cp1252', errors='replace')
                return fromstring(clean_ascii_chars(raw))
                
            isbn = check_isbn(identifiers.get('isbn', None))

            # If there's an ISBN, search by ISBN first
            if isbn:
                query = self.create_query(log, identifiers=identifiers)
            
                log.info('Querying: %s' % query)
                self._parse_search_results(log, html_from_url(query), matches, relevance, 1, timeout)

            # If we haven't reached the maximum number of results, also search for 
            if len(matches) < MAX_RESULTS:
                title = get_udc().decode(title)
                authors = authors or []
                authors = [get_udc().decode(a) for a in authors]
                query = self.create_query(log, title=title, authors=authors)
            
                log.info('Querying: %s' % query)
                self._parse_search_results(log, html_from_url(query), matches, relevance, 2, timeout)

        if abort.is_set():
            return

        from calibre_plugins.isfdb2.worker import Worker
        workers = [Worker(url, result_queue, br, log, relevance[url], self) for url in matches]

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
        
        return None

    def _parse_search_results(self, log, root, matches, relevance_dict, relevance, timeout):
        '''This function doesn't filter the results in any way; we may
        put some filtering back in later if it's actually necessary.'''
        
        results = root.xpath('//div[@id="main"]/table/tr')
        if not results:
            log.info('Unable to parse search results.')
            return

        for result in results:
            if not result.xpath('td'):
                continue # header
                
            result_url = ''.join(result.xpath('td[1]/a/@href'))

            if result_url:
                matches.add(result_url)
                relevance_dict[result_url] = relevance
                
                if len(matches) >= MAX_RESULTS:
                    break

    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30):
        cached_url = self.get_cached_cover_url(identifiers)
        
        if not cached_url:
            log.info('No cached cover found, running identify')
            rq = Queue()
            self.identify(log, rq, abort, title=title, authors=authors, identifiers=identifiers)
            
            if abort.is_set():
                return

            results = []

            while True:
                try:
                    results.append(rq.get_nowait())
                except Empty:
                    break

            results.sort(key=self.identify_results_keygen(title=title, authors=authors, identifiers=identifiers))

            for mi in results:
                cached_url = self.get_cached_cover_url(mi.identifiers)
                if cached_url is not None:
                    break
                    
        if not cached_url:
            log.info('No cover found')
            return

        if abort.is_set():
            return
        
        br = self.browser
        log.info('Downloading cover from:', cached_url)

        try:
            cdata = br.open_novisit(cached_url, timeout=timeout).read()
            result_queue.put((self, cdata))
        except:
            log.exception('Failed to download cover from:', cached_url)


if __name__ == '__main__': # tests
    # To run these test use:
    # calibre-debug -e __init__.py
    from calibre import prints
    from calibre.ebooks.metadata.sources.test import (test_identify_plugin, title_test, authors_test)

    def cover_test(cover_url):
        if cover_url is not None:
            cover_url = cover_url.lower()

        def test(mi):
            mc = mi.cover_url
            if mc is not None:
                mc = mc.lower()
            if mc == cover_url:
                return True
            prints('Cover test failed. Expected: \'%s\' found: ' % cover_url, mc)
            return False
        return test

    # Test the plugin.
    test_identify_plugin(ISFDB2.name,
        [
            (# A book with an ISBN
                {'identifiers':{'isbn': '9780345470638'},
                    'title':'Black House', 'authors':['Stephen King', 'Peter Straub']},
                [title_test('Black House', exact=True),
                 authors_test(['Stephen King', 'Peter Straub']),
                 cover_test('http://images.amazon.com/images/P/034547063X.01.LZZZZZZZ.jpg')]
            ),

            (# A book with no ISBN specified
                {'title':'Black House', 'authors':['Stephen King', 'Peter Straub']},
                [title_test('Black House', exact=True),
                 authors_test(['Stephen King', 'Peter Straub']),
                 cover_test('http://images.amazon.com/images/P/034547063X.01.LZZZZZZZ.jpg')]
            ),

            (# A book with an ISFDB ID
                {'identifiers':{'isfdb': '4638'},
                    'title':'Black House', 'authors':['Stephen King', 'Peter Straub']},
                [title_test('Black House', exact=True),
                 authors_test(['Stephen King', 'Peter Straub']),
                 cover_test('http://images.amazon.com/images/P/034547063X.01.LZZZZZZZ.jpg')]
            )
        ], fail_missing_meta=False)
