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
import datetime
import re

from urllib import quote, urlencode
from Queue import Queue, Empty
from threading import Thread

from lxml.html import fromstring, tostring

from calibre.ebooks.metadata import check_isbn
from calibre.ebooks.metadata.sources.base import Source, Option
from calibre.ebooks.metadata.book.base import Metadata

from calibre.library.comments import sanitize_comments_html

from calibre.utils.cleantext import clean_ascii_chars
from calibre.utils.localization import get_udc
from calibre.utils.date import utc_tz


class ISFDB2(Source):
    name = 'ISFDB2'
    description = _('Downloads metadata and covers from ISFDB')
    author = 'Adrianna Pińska'
    version = (1, 0, 0)
    minimum_calibre_version = (0, 9, 33)

    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset(['title', 'authors', 'identifier:isfdb', 'identifier:isfdb-catalog', 'identifier:isbn', 'publisher', 'pubdate', 'comments'])

    options = (
        Option(
            'max_results',
            'number',
            5,
            _('Maximum number of search results to download:'),
            _('This setting only applies to ISBN and title / author searches. Book records with a valid ISFDB ID will return exactly one result.'),
        ),
    )

    has_html_comments = True
    supports_gzip_transfer_encoding = False
    cached_cover_url_is_reliable = True

    SEARCH_URL = 'http://www.isfdb.org/cgi-bin/se.cgi?%s'
    ADV_SEARCH_URL = 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?%s'
    ID_URL = 'http://www.isfdb.org/cgi-bin/pl.cgi?%s'

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

    def _max_results(self):
        # At least one result, and no more than 10
        return max(min(self.prefs["max_results"], 10), 1)

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

            # If we haven't reached the maximum number of results, also search by title and author
            if len(matches) < self._max_results():
                title = get_udc().decode(title)
                authors = authors or []
                authors = [get_udc().decode(a) for a in authors]
                query = self.create_query(log, title=title, authors=authors)
            
                log.info('Querying: %s' % query)
                self._parse_search_results(log, html_from_url(query), matches, relevance, 2, timeout)

        if abort.is_set():
            return

        workers = [Worker(m, result_queue, br, log, relevance[m], self) for m in matches]

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
                
                if len(matches) >= self._max_results():
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
            self.get_details()
        except Exception as e:
            self.log.exception('get_details failed in worker for url %r with error %r' % (self.url, e))

    def get_details(self):
        # TODO stripping out all exception handling; may put some back when we see what exceptions we get
        self.log.info('Worker fetching ISFDB url: %r' % self.url)
        
        response = self.browser.open_novisit(self.url, timeout=self.timeout).read()
        raw = response.decode('cp1252', errors='replace')
        root = fromstring(clean_ascii_chars(raw))

        isfdb_id = None
        try:
            isfdb_id = re.search('(\d+)$', self.url).groups(0)[0]
        except:
            self.log.exception('Error parsing ISFDB ID for url: %r' % self.url)
            
        title = None
        authors = []
        isbn = None
        publisher = None
        pubdate = None
        catalog_id = None
        
        detail_nodes = root.xpath('//div[@id="content"]//td[@class="pubheader"]/ul/li')
        
        if not detail_nodes:
            detail_nodes = root.xpath('//div[@id="content"]/div/ul/li') # no table (on records with no image)

        for detail_node in detail_nodes:
            section = detail_node[0].text_content().strip().rstrip(':')
            #self.log.info(section)
            try:
                if section == 'Publication':
                    title = detail_node[0].tail.strip()
                    if not title:
                        # assume an extra span with a transliterated title tooltip
                        title = detail_node[1].text_content().strip()
                    #self.log.info(title)
                elif section == 'Authors' or section == 'Editors':
                    for a in detail_node.xpath('.//a'):
                        author = a.text_content().strip()
                        if section.startswith('Editors'):
                            authors.append(author + ' (Editor)')
                        else:
                            authors.append(author)
                    #self.log.info(authors)
                elif section == 'ISBN':
                    isbn = detail_node[0].tail.strip('[] \n')
                    #self.log.info(isbn)
                elif section == 'Publisher':
                    publisher = detail_node.xpath('a')[0].text_content().strip()
                    #self.log.info(publisher)
                elif section == 'Date':                    
                    pubdate = self._convert_date_text(detail_node[0].tail.strip())
                    #self.log.info(pubdate)
                elif section == 'Catalog ID':
                    # UNTESTED
                    catalog_id = detail_node[1].text_content().strip()
                    #self.log.info(catalog_id)
            except:
                self.log.exception('Error parsing section %r for url: %r' % (section, self.url) )

        if not title or not authors or not isfdb_id:
            self.log.error('Insufficient metadata found for %r' % self.url)
            return

        mi = Metadata(title, authors)
        mi.set_identifier('isfdb', isfdb_id)

        if isbn:
            mi.isbn = isbn
        if publisher:
            mi.publisher = publisher
        if pubdate:
            mi.pubdate = pubdate
        if catalog_id:
            mi.set_identifier('isfdb-catalog', catalog_id)
            
        try:
            contents_node = root.xpath('//div[@class="ContentBox"][2]/ul')
            
            if contents_node:
                contents = tostring(contents_node[0], method='html')            
                mi.comments = sanitize_comments_html(contents)

        except:
            self.log.exception('Error parsing comments for url: %r'%self.url)

        try:
            img_src = root.xpath('//div[@id="content"]//table/tr[1]/td[1]/a/img/@src')
            if img_src:
                mi.cover_url = img_src[0]
                self.plugin.cache_identifier_to_cover_url(self.isfdb_id, mi.cover_url)
        except:
            self.log.exception('Error parsing cover for url: %r'%self.url)
        
        mi.has_cover = bool(mi.cover_url)

        mi.source_relevance = self.relevance

        # TODO: do we actually want / need this?
        if isfdb_id:
            if isbn:
                self.plugin.cache_isbn_to_identifier(isbn, isfdb_id)

        self.plugin.clean_downloaded_metadata(mi)
        self.result_queue.put(mi)

    def _convert_date_text(self, date_text):
        # We use this instead of strptime to handle dummy days and months
        # E.g. 1965-00-00
        try:
            year, month, day = [int(p) for p in date_text.split(":")]

            if month == 0:
                month = 1

            if day == 0:
                day = 1
            
            return datetime.datetime(year, month, day, tzinfo=utc_tz)
        except:
            return None # not a parseable date


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
