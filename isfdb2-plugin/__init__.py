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

from calibre_plugins.isfdb.objects import Publication, PublicationsList, TitleList, TitleCovers


class ISFDB(Source):
    name = 'ISFDB'
    description = _('Downloads metadata and covers from ISFDB')
    author = 'Adrianna Pińska'
    version = (2, 0, 0)
    minimum_calibre_version = (0, 9, 33)

    capabilities = frozenset(['identify', 'cover'])
    touched_fields = frozenset(['title', 'authors', 'identifier:isfdb', 'identifier:isfdb-catalog', 'identifier:isfdb-title', 'identifier:isbn', 'publisher', 'pubdate', 'comments'])

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

    # TODO: delegate to helper objects
    #SEARCH_URL = 'http://www.isfdb.org/cgi-bin/se.cgi?%s'
    #ADV_SEARCH_URL = 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?%s'
    #ID_URL = 'http://www.isfdb.org/cgi-bin/pl.cgi?%s'

    def get_book_url(self, identifiers):
        isfdb_id = identifiers.get('isfdb', None)
        if isfdb_id:
            #url = self.ID_URL % isfdb_id
            url = Publication.url_from_id(isfdb_id)
            return ('isfdb', isfdb_id, url)

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

        # If we have an ISFDB ID, we use it to construct the publication URL directly
        
        isfdb_id = identifiers.get('isfdb', None)
        if isfdb_id:
            _, _, url = self.get_book_url(identifiers)
            matches.add(url)
            relevance[url] = 0 # most relevant
        else:
            isbn = check_isbn(identifiers.get('isbn', None))

            # If there's an ISBN, search by ISBN first
            if isbn:
                query = PublicationsList.url_from_isbn(isbn)
                urls = PublicationsList.from_url(self.browser, query, timeout, log)
                
                for url in urls:
                    matches.add(url)
                    relevance[url] = 1
                    
                    if len(matches) >= self._max_results():
                        break
                
            # If we haven't reached the maximum number of results, also search by title and author
            if len(matches) < self._max_results():
                title = get_udc().decode(title)
                authors = authors or []
                authors = [get_udc().decode(a) for a in authors]
                
                title_tokens = self.get_title_tokens(title, strip_joiners=False, strip_subtitle=True)
                author_tokens = self.get_author_tokens(authors, only_first_author=True)
                
                query = PublicationsList.url_from_title_and_authors(title_tokens, author_tokens)
                urls = PublicationsList.from_url(self.browser, query, timeout, log)
                
                for url in urls:
                    matches.add(url)
                    relevance[url] = 2
                    
                    if len(matches) >= self._max_results():
                        break

        if abort.is_set():
            return

        workers = [Worker(m, result_queue, self.browser, log, relevance[m], self) for m in matches]

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

    def download_cover(self, log, result_queue, abort, title=None, authors=None, identifiers={}, timeout=30):
        cached_url = self.get_cached_cover_url(identifiers)
        
        if not cached_url:
            # TODO: fetch the covers from the title covers page instead!
            # how do we get from publication to title?
            # cache a title identifier from the publication details if it exists
            # but check if the name / author match
            # otherwise do a title query with exact title and author name
            # and filter out only book results (NOVEL, ANTHOLOGY, COLLECTION???)
            # (what about anthologies? what gets entered as the author name?)
            # then take the first result, parse out title ids, and pass to workers
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
        
        log.info('Downloading cover from:', cached_url)

        try:
            cdata = self.browser.open_novisit(cached_url, timeout=timeout).read()
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
            response = self.browser.open_novisit(self.url, timeout=self.timeout).read()
            raw = response.decode('cp1252', errors='replace')
            root = fromstring(clean_ascii_chars(raw))

            # TODO alternatively, parse a title cover page
            self.parse_publication(root)
        except Exception as e:
            self.log.exception('Worker failed to fetch and parse url %r with error %r' % (self.url, e))

    # TODO: should all these parsing functions be class methods on a parser object instead?
    # Maybe we should have helper objects to store all this state?
    # Objects for Publication, Title, Publications, Titles, Title Covers, which know how to parse themselves and return dicts of info?

    def parse_title_covers(self):
        pass # TODO: this will be a function parsing a title covers page

    def parse_publication(self, root):
        self.log.info('Worker parsing ISFDB url: %r' % self.url)
        
        isfdb_id = None
        try:
            isfdb_id = re.search('(\d+)$', self.url).groups(0)[0]
        except:
            self.log.exception('Error parsing ISFDB ID for url: %r' % self.url)

        # TODO TODO TODO middle of refactoring
        
        #title = None
        #authors = []
        
        #isbn = None
        #publisher = None
        #pubdate = None
        #catalog_id = None
        #title_id = None
        
        detail_nodes = root.xpath('//div[@id="content"]//td[@class="pubheader"]/ul/li')
        
        if not detail_nodes:
            detail_nodes = root.xpath('//div[@id="content"]/div/ul/li') # no table (on records with no image)

        detail_dict = dict((n[0].text_content().strip().rstrip(':'), n) for n in detail_nodes)

        # Title and author are compulsory, so if we can't parse these we abort

        title_node = detail_dict.pop("Publication")
        title = title_node[0].tail.strip()
        if not title:
            # assume an extra span with a transliterated title tooltip
            title = title_node[1].text_content().strip()

        if "Authors" in detail_dict:
            author_node = detail_dict.pop("Authors")
        

        # TODO: put these in a dict, process title and authors first, then process the rest, removing intermediate variables
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
                    date_text = detail_node[0].tail.strip()
                    # We use this instead of strptime to handle dummy days and months
                    # E.g. 1965-00-00
                    year, month, day = [int(p) for p in date_text.split("-")]
                    month = month or 1
                    day = day or 1
                    pubdate = datetime.datetime(year, month, day, tzinfo=utc_tz)
                    #self.log.info(pubdate)
                elif section == 'Catalog ID':
                    # UNTESTED
                    catalog_id = detail_node[1].text_content().strip()
                    #self.log.info(catalog_id)
                elif section == 'Container Title':
                    title_url = detail_nodes[9].xpath('a')[0].attrib.get('href')
                    title_id = re.search('(\d+)$', title_url).groups(0)[0]
                    #self.log.info(title_id)
            except:
                self.log.exception('Error parsing section %r for url: %r' % (section, self.url) )

        if not title or not authors or not isfdb_id:
            self.log.error('Insufficient metadata found for %r' % self.url)
            return

        mi = Metadata(title, authors)
        mi.set_identifier('isfdb', isfdb_id)

        #if isbn:
            #mi.isbn = isbn
        #if publisher:
            #mi.publisher = publisher
        #if pubdate:
            #mi.pubdate = pubdate
        #if catalog_id:
            #mi.set_identifier('isfdb-catalog', catalog_id)
        #if title_id:
            #mi.set_identifier('isfdb-title', title_id)
            
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
                self.plugin.cache_identifier_to_cover_url(isfdb_id, mi.cover_url)
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
    # TODO: new test cases
    # by id
    # by isbn
    # by author / title
    # anthology
    # with cover
    # without cover
    test_identify_plugin(ISFDB.name,
        [
            #(# A book with an ISBN
                #{'identifiers':{'isbn': '9780345470638'},
                    #'title':'Black House', 'authors':['Stephen King', 'Peter Straub']},
                #[title_test('Black House', exact=True),
                 #authors_test(['Stephen King', 'Peter Straub']),
                 #cover_test('http://images.amazon.com/images/P/034547063X.01.LZZZZZZZ.jpg')]
            #),

            #(# A book with no ISBN specified
                #{'title':'Black House', 'authors':['Stephen King', 'Peter Straub']},
                #[title_test('Black House', exact=True),
                 #authors_test(['Stephen King', 'Peter Straub']),
                 #cover_test('http://images.amazon.com/images/P/034547063X.01.LZZZZZZZ.jpg')]
            #),

            #(# A book with an ISFDB ID
                #{'identifiers':{'isfdb': '4638'},
                    #'title':'Black House', 'authors':['Stephen King', 'Peter Straub']},
                #[title_test('Black House', exact=True),
                 #authors_test(['Stephen King', 'Peter Straub']),
                 #cover_test('http://images.amazon.com/images/P/034547063X.01.LZZZZZZZ.jpg')]
            #)
        ], fail_missing_meta=False)
