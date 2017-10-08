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
from collections import OrderedDict
from threading import Thread

from lxml.html import fromstring, tostring

from calibre.ebooks.metadata.book.base import Metadata
from calibre.library.comments import sanitize_comments_html
from calibre.utils.cleantext import clean_ascii_chars

import calibre_plugins.isfdb.config as cfg

class Worker(Thread): # Get details

    '''
    Get book details from ISFDB book page in a separate thread.
    '''

    def __init__(self, url, result_queue, browser, log, relevance, plugin, timeout=20):
        print("Ohai")
        Thread.__init__(self)
        self.daemon = True
        self.url, self.result_queue = url, result_queue
        self.log, self.timeout = log, timeout
        self.relevance, self.plugin = relevance, plugin
        self.browser = browser.clone_browser()
        self.cover_url = self.isfdb_id = self.isbn = None

    def run(self):
        print("Ohai")
        try:
            self.get_details()
        except:
            self.log.exception('get_details failed for url: %r'%self.url)

    def get_details(self):
        try:
            print('ISFDB url: %r'%self.url)
            self.log.info('ISFDB url: %r'%self.url)
            raw = self.browser.open_novisit(self.url, timeout=self.timeout).read().strip()
        except Exception as e:
            if callable(getattr(e, 'getcode', None)) and \
                    e.getcode() == 404:
                self.log.error('URL malformed: %r'%self.url)
                return
            attr = getattr(e, 'args', [None])
            attr = attr if attr else [None]
            if isinstance(attr[0], socket.timeout):
                msg = 'ISFDB.org timed out. Try again later.'
                self.log.error(msg)
            else:
                msg = 'Failed to make details query: %r'%self.url
                self.log.exception(msg)
            return

        raw = raw.decode('cp1252', errors='replace')

        if '<title>404 - ' in raw:
            self.log.error('URL malformed: %r'%self.url)
            return

        try:
            root = fromstring(clean_ascii_chars(raw))
        except:
            msg = 'Failed to parse ISFDB details page: %r'%self.url
            self.log.exception(msg)
            return

        self.parse_details(root)

    def parse_details(self, root):
        isfdb_id = None
        title = None
        authors = []
        isbn = None
        publisher = None
        pubdate = None
        
        try:
            isfdb_id = re.search('(\d+)$', self.url).groups(0)[0]
        except:
            self.log.exception('Error parsing ISFDB ID for url: %r' % self.url)
        
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
            self.log.error('Could not find title/authors/ISFDB ID for %r' % self.url)
            self.log.error('ISFDB: %r Title: %r Authors: %r' % (isfdb_id, title,
                authors))
            return

        mi = Metadata(title, authors)
        mi.set_identifier('isfdb', isfdb_id)
        self.isfdb_id = isfdb_id

        if isbn:
            self.isbn = mi.isbn = isbn
        if publisher:
            mi.publisher = publisher
        if pubdate:
            mi.pubdate = pubdate
            
        try:
            mi.comments = self.parse_comments(root)
        except:
            self.log.exception('Error parsing comments for url: %r'%self.url)

        try:
            self.cover_url = self.parse_cover(root)
        except:
            self.log.exception('Error parsing cover for url: %r'%self.url)
        
        mi.has_cover = bool(self.cover_url)
        mi.cover_url = self.cover_url # This is purely so we can run a test for it!!!

        mi.source_relevance = self.relevance

        if self.isfdb_id:
            if self.isbn:
                self.plugin.cache_isbn_to_identifier(self.isbn, self.isfdb_id)

        self.plugin.clean_downloaded_metadata(mi)
        self.result_queue.put(mi)

    def _convert_date_text(self, date_text):
        # 2008-08-00
        try:
            year = int(date_text[0:4])
            month = int(date_text[5:7])
            if month == 0:
                month = 1
            day = int(date_text[8:10])
            if day == 0:
                day = 1
            from calibre.utils.date import utc_tz
            pubdate = datetime.datetime(year, month, day, tzinfo=utc_tz)
            return pubdate
        except:
            return None # not a parseable date

    def parse_comments(self, root):
        default_append_contents = cfg.DEFAULT_STORE_VALUES[cfg.KEY_APPEND_CONTENTS]
        append_contents = cfg.plugin_prefs[cfg.STORE_NAME].get(cfg.KEY_APPEND_CONTENTS, default_append_contents)
        comments = ''
        if append_contents:
            contents_node = root.xpath('//div[@class="ContentBox"][2]/ul')
            if contents_node:
                contents = tostring(contents_node[0], method='html')
                comments += contents
        if comments:
            return comments

    def parse_cover(self, root):
        img_src = root.xpath('//div[@id="content"]//table/tr[1]/td[1]/a/img/@src')
        if img_src:
            page_url = img_src[0]
            self.plugin.cache_identifier_to_cover_url(self.isfdb_id, page_url)
            return page_url
