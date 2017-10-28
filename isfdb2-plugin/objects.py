#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '''(c) 2017 Adrianna Pińska <adrianna.pinska@gmail.com>,
Xtina Schelin <xtina.schelin@gmail.com>,
Grant Drake <grant.drake@gmail.com>'''
__docformat__ = 'restructuredtext en'

import re
from lxml.html import fromstring, tostring
from calibre.utils.cleantext import clean_ascii_chars
from urllib import quote, urlencode

class ISFDBObject(object):
    ADV_SEARCH_URL = 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?%s'
    ID_URL = 'http://www.isfdb.org/cgi-bin/pl.cgi?%s'
    TITLE_URL = 'http://www.isfdb.org/cgi-bin/title.cgi?%s'
    TITLE_COVERS_URL = 'http://www.isfdb.org/cgi-bin/titlecovers.cgi?%s'
    
    @classmethod
    def root_from_url(cls, browser, url, timeout, log):
        log.info('Fetching: %s' % url)
        response = browser.open_novisit(url, timeout=timeout)
        raw = response.read().decode('cp1252', errors='replace')
        return fromstring(clean_ascii_chars(raw))

    @classmethod
    def url_from_advanced_search(cls, params):
        return cls.ADV_SEARCH_URL % urlencode(params)


class PublicationsList(ISFDBObject, list):
    def __init__(self, publication_urls):
        list.__init__(self, publication_urls)

    @classmethod
    def url_from_isbn(cls, isbn):
        params = {
            "USE_1": "pub_isbn",
            "OPERATOR_1": "exact",
            "TERM_1": isbn,
            "ORDERBY": "pub_title",
            "START": "0",
            "TYPE": "Publication",
        }
        
        return cls.url_from_advanced_search(params)
    
    @classmethod    
    def url_from_title_and_authors(cls, title_tokens, author_tokens):
        # see if this makes an actual difference
        #title_tokens = [quote(t.encode('utf-8') if isinstance(t, unicode) else t) for t in title_tokens]
        #author_tokens = [quote(t.encode('utf-8') if isinstance(t, unicode) else t) for t in author_tokens]
        title = '+'.join(title_tokens)
        authors = '+'.join(author_tokens)
        
        params = {
            "USE_1": "pub_title",
            "OPERATOR_1": "contains",
            "TERM_1": title,
            "CONJUNCTION_1": "AND",
            "USE_2": "author_canonical",
            "OPERATOR_2": "contains",
            "TERM_2": authors,
            "ORDERBY": "pub_title",
            "START": "0",
            "TYPE": "Publication",
        }
        
        return cls.url_from_advanced_search(params)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        publication_urls = []
        
        root = cls.root_from_url(browser, url, timeout, log)
        rows = root.xpath('//div[@id="main"]/table/tr')
        
        for row in rows:
            if not row.xpath('td'):
                continue # header
                
            url = ''.join(row.xpath('td[1]/a/@href'))
            
            publication_urls.append(url)
            
        return cls(publication_urls)



class TitleList(ISFDBObject, list):
    def __init__(self, title_urls):
        list.__init__(self, title_urls)
    
    @classmethod    
    def url_from_title_and_authors(cls, title_tokens, author_tokens):
        # see if this makes an actual difference
        #title_tokens = [quote(t.encode('utf-8') if isinstance(t, unicode) else t) for t in title_tokens]
        #author_tokens = [quote(t.encode('utf-8') if isinstance(t, unicode) else t) for t in author_tokens]
        title = '+'.join(title_tokens)
        authors = '+'.join(author_tokens)
        
        params = {
            "USE_1": "title_title",
            "OPERATOR_1": "exact",
            "TERM_1": title,
            "CONJUNCTION_1": "AND",
            "USE_2": "author_canonical",
            "OPERATOR_2": "contains",
            "TERM_2": authors,
            "ORDERBY": "title_title",
            "START": "0",
            "TYPE": "Title",
        }
        
        return cls.url_from_advanced_search(params)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        title_urls = []
        
        root = cls.root_from_url(browser, url, timeout, log)
        rows = root.xpath('//div[@id="main"]/table/tr')

        for row in rows:
            if not row.xpath('td'):
                continue # header
                
            url = ''.join(row.xpath('td[5]/a/@href'))
            
            title_urls.append(url)
            
        return cls(title_urls)


class Publication(ISFDBObject):
    @classmethod
    def url_from_id(cls, isfdb_id):
        return cls.ID_URL % isfdb_id
        
    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).groups(0)[0]

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        root = cls.root_from_url(browser, url, timeout, log)
        pass # return parsed object


class TitleCovers(ISFDBObject):
    @classmethod
    def url_from_id(cls, title_id):
        return cls.TITLE_COVERS_URL % title_id
        
    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).groups(0)[0]

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        root = cls.root_from_url(browser, url, timeout, log)
        pass # return parsed object
