#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '''(c) 2017 Adrianna Pińska <adrianna.pinska@gmail.com>,
Xtina Schelin <xtina.schelin@gmail.com>,
Grant Drake <grant.drake@gmail.com>'''
__docformat__ = 'restructuredtext en'

import socket, re, datetime
from threading import Thread

from lxml.html import fromstring, tostring

from calibre.ebooks.metadata.book.base import Metadata
from calibre.library.comments import sanitize_comments_html
from calibre.utils.cleantext import clean_ascii_chars

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

        self.parse_details(root)

    def parse_details(self, root):
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
            except:
                self.log.exception('Error parsing section %r for url: %r' % (section, self.url) )

        if not title or not authors or not isfdb_id:
            self.log.error('Insufficient metadata found for %r' % self.url)
            return

        mi = Metadata(title, authors)
        mi.set_identifier('isfdb', isfdb_id)
        # TODO: should we also extract old-timey pre-ISBN catalog identifiers from book records that have them?

        if isbn:
            mi.isbn = isbn
        if publisher:
            mi.publisher = publisher
        if pubdate:
            mi.pubdate = pubdate
            
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
                self.plugin.cache_identifier_to_cover_url(self.isfdb_id, page_url)
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
            
            from calibre.utils.date import utc_tz
            return datetime.datetime(year, month, day, tzinfo=utc_tz)
        except:
            return None # not a parseable date

