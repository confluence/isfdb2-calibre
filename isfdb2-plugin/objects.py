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
import datetime

from lxml.html import fromstring, tostring
from urllib import urlencode

from calibre.utils.cleantext import clean_ascii_chars
from calibre.library.comments import sanitize_comments_html

class ISFDBObject(object):
    @classmethod
    def root_from_url(cls, browser, url, timeout, log):
        log.info('Fetching: %s' % url)
        response = browser.open_novisit(url, timeout=timeout)
        raw = response.read().decode('cp1252', errors='replace')
        return fromstring(clean_ascii_chars(raw))


class SearchResults(ISFDBObject):
    URL = 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?';
    TYPE = None;

    @classmethod
    def url_from_params(cls, params):
        return cls.URL + urlencode(params)
    
    @classmethod
    def is_type_of(cls, url):
        return url.startswith(cls.URL) and ("TYPE=%s" % cls.TYPE) in url
    

class PublicationsList(SearchResults):
    TYPE = "Publication"
    
    @classmethod
    def url_from_isbn(cls, isbn):
        # TODO support adding price or date as a supplementary field
        # but where will it go in the interface?
        params = {
            "USE_1": "pub_isbn",
            "OPERATOR_1": "exact",
            "TERM_1": isbn,
            "ORDERBY": "pub_title",
            "START": "0",
            "TYPE": cls.TYPE,
        }

        return cls.url_from_params(params)

    @classmethod
    def url_from_title_and_author(cls, title_tokens, author_tokens):
        # TODO support adding price or date as a supplementary field
        # but where will it go in the interface?
        title = ' '.join(title_tokens)
        author = ' '.join(author_tokens)

        field = 0

        params = {
            "ORDERBY": "pub_title",
            "START": "0",
            "TYPE": cls.TYPE,
        }

        if title:
            field += 1
            params.update({
                "USE_%d" % field: "pub_title",
                "OPERATOR_%d" % field: "contains",
                "TERM_%d" % field: title,
            })

        if author:
            field += 1
            params.update({
                "USE_%d" % field: "author_canonical",
                "OPERATOR_%d" % field: "contains",
                "TERM_%d" % field: author,
            })

        if "USE_2" in params:
            params.update({
                "CONJUNCTION_1": "AND",
            })

        return cls.url_from_params(params)

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

        log.info("Parsed publications from url %r. Found %d publications." % (url, len(publication_urls)))

        return publication_urls



class TitleList(SearchResults):
    # TODO: separate permissive title/author search from specific lookup of a publication
    # TODO: isbn not possible; add type to exact search?
    
    TYPE = "Title"
    
    @classmethod
    def url_from_exact_title_author_and_type(cls, title, author, ttype):
        params = {
            "USE_1": "title_title",
            "OPERATOR_1": "exact",
            "TERM_1": title,
            "CONJUNCTION_1": "AND",
            "USE_2": "author_canonical",
            "OPERATOR_2": "exact",
            "TERM_2": author,
            "CONJUNCTION_2": "AND",
            "USE_3": "title_ttype",
            "OPERATOR_3": "exact",
            "TERM_3": ttype,
            "ORDERBY": "title_title",
            "START": "0",
            "TYPE": cls.TYPE,
        }

        return cls.url_from_params(params)
    
    @classmethod
    def url_from_title_and_author(cls, title_tokens, author_tokens):
        title = ' '.join(title_tokens)
        author = ' '.join(author_tokens)

        params = {
            "USE_1": "title_title",
            "OPERATOR_1": "contains",
            "TERM_1": title,
            "CONJUNCTION_1": "AND",
            "USE_2": "author_canonical",
            "OPERATOR_2": "contains",
            "TERM_2": author,
            "ORDERBY": "title_title",
            "START": "0",
            "TYPE": cls.TYPE,
        }

        return cls.url_from_params(params)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        title_urls = []

        root = cls.root_from_url(browser, url, timeout, log)
        rows = root.xpath('//div[@id="main"]/form/table/tr')

        for row in rows:
            if not row.xpath('td'):
                continue # header

            url = ''.join(row.xpath('td[5]/a/@href'))

            title_urls.append(url)

        log.info("Parsed titles from url %r. Found %d titles." % (url, len(title_urls)))

        return title_urls


class Record(ISFDBObject):
    URL = None
    
    @classmethod
    def is_type_of(cls, url):
        return url.startswith(cls.URL)


class Publication(Record):
    URL = 'http://www.isfdb.org/cgi-bin/pl.cgi?'

    @classmethod
    def url_from_id(cls, isfdb_id):
        return cls.URL + isfdb_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        properties = {}
        properties["isfdb"] = cls.id_from_url(url)

        root = cls.root_from_url(browser, url, timeout, log)

        # Records with a cover image
        detail_nodes = root.xpath('//div[@id="content"]//td[@class="pubheader"]/ul/li')
        # Records without a cover image
        if not detail_nodes:
            detail_nodes = root.xpath('//div[@id="content"]/div/ul/li') # no table (on records with no image)

        for detail_node in detail_nodes:
            section = detail_node[0].text_content().strip().rstrip(':')
            try:
                if section == 'Publication':
                    properties["title"] = detail_node[0].tail.strip()
                    if not properties["title"]:
                        # assume an extra span with a transliterated title tooltip
                        properties["title"] = detail_node[1].text_content().strip()
                elif section in ('Author', 'Authors', 'Editor', 'Editors'):
                    properties["authors"] = []
                    for a in detail_node.xpath('.//a'):
                        author = a.text_content().strip()
                        
                        # For looking up the corresponding title.
                        # We can only use the first author because the search is broken.
                        if "author_string" not in properties:
                            properties["author_string"] = author
                            
                        if section.startswith('Editor'):
                            properties["authors"].append(author + ' (Editor)')
                        else:
                            properties["authors"].append(author)
                elif section == 'Type':
                    properties["type"] = detail_node[0].tail.strip()
                elif section == 'ISBN':
                    properties["isbn"] = detail_node[0].tail.strip('[] \n')
                elif section == 'Publisher':
                    properties["publisher"] = detail_node.xpath('a')[0].text_content().strip()
                elif section == 'Date':
                    date_text = detail_node[0].tail.strip()
                    # We use this instead of strptime to handle dummy days and months
                    # E.g. 1965-00-00
                    year, month, day = [int(p) for p in date_text.split("-")]
                    month = month or 1
                    day = day or 1
                    properties["pubdate"] = datetime.datetime(year, month, day)
                elif section == 'Catalog ID':
                    properties["isfdb-catalog"] = detail_node[0].tail.strip()
                elif section == 'Container Title':
                    title_url = detail_nodes[9].xpath('a')[0].attrib.get('href')
                    properties["isfdb-title"] = Title.id_from_url(title_url)
            except Exception as e:
                log.exception('Error parsing section %r for url: %r. Error: %r' % (section, url, e) )

        try:
            contents_node = root.xpath('//div[@class="ContentBox"][2]/ul')

            if contents_node:
                properties["comments"] = sanitize_comments_html(tostring(contents_node[0], method='html'))
        except Exception as e:
            log.exception('Error parsing comments for url: %r. Error: %r' % (url, e))

        try:
            img_src = root.xpath('//div[@id="content"]//table/tr[1]/td[1]/a/img/@src')
            if img_src:
                properties["cover_url"] = img_src[0]
        except Exception as e:
            log.exception('Error parsing cover for url: %r. Error: %r' % (url, e))

        return properties


class TitleCovers(Record):
    URL = 'http://www.isfdb.org/cgi-bin/titlecovers.cgi?'
    
    @classmethod
    def url_from_id(cls, title_id):
        return cls.URL + title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        root = cls.root_from_url(browser, url, timeout, log)
        return root.xpath('//div[@id="main"]/a/img/@src')


class Title(Record):
    URL = 'http://www.isfdb.org/cgi-bin/title.cgi?'
    
    @classmethod
    def url_from_id(cls, isfdb_title_id):
        return cls.URL + isfdb_title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        properties = {}
        properties["isfdb-title"] = cls.id_from_url(url)

        root = cls.root_from_url(browser, url, timeout, log)
        
        detail_div = root.xpath('//div[@class="ContentBox"]')[0]
        
        detail_nodes = []
        detail_node = []
        for e in detail_div:
            if e.tag == 'br':
                detail_nodes.append(detail_node)
                detail_node = []
            else:
                detail_node.append(e)
        detail_nodes.append(detail_node)
                
        for detail_node in detail_nodes:
            section = detail_node[0].text_content().strip().rstrip(':')
            try:
                if section == 'Title':
                    properties["title"] = detail_node[0].tail.strip()
                    if not properties["title"]:
                        # assume an extra span with a transliterated title tooltip
                        properties["title"] = detail_node[1].text_content().strip()
                elif section in ('Author', 'Authors', 'Editor', 'Editors'):
                    properties["authors"] = []
                    author_links = [e for e in detail_node if e.tag == 'a']
                    for a in author_links:
                        author = a.text_content().strip()
                        
                        if section.startswith('Editor'):
                            properties["authors"].append(author + ' (Editor)')
                        else:
                            properties["authors"].append(author)
                elif section == 'Type':
                    properties["type"] = detail_node[0].tail.strip()
                elif section == 'Date':
                    date_text = detail_node[0].tail.strip()
                    # We use this instead of strptime to handle dummy days and months
                    # E.g. 1965-00-00
                    year, month, day = [int(p) for p in date_text.split("-")]
                    month = month or 1
                    day = day or 1
                    properties["pubdate"] = datetime.datetime(year, month, day)
                elif section == 'Series':
                    properties["series"] = detail_node[1].text_content().strip()
                elif section == 'Series Number':
                    properties["series_index"] = float(detail_node[0].tail.strip())
                elif section == 'Current Tags':
                    properties["tags"] = []
                    tag_links = [e for e in detail_node if e.tag == 'a']
                    for a in tag_links:
                        tag = a.text_content().strip()
                        if tag != "Add Tags":
                            properties["tags"].append(tag)

            except Exception as e:
                log.exception('Error parsing section %r for url: %r. Error: %r' % (section, url, e) )

        return properties
