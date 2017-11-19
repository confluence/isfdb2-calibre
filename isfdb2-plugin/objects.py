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


class PublicationsList(ISFDBObject):
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
            "TYPE": "Publication",
        }

        return cls.url_from_advanced_search(params)

    @classmethod
    def url_from_title_and_author(cls, title_tokens, author_tokens):
        # TODO support adding price or date as a supplementary field
        # but where will it go in the interface?
        title = ' '.join(title_tokens)
        author = ' '.join(author_tokens)

        title = re.sub(r"(.+),? (The|A|An)$", r"\2 \1", title, flags=re.IGNORECASE)

        field = 0

        params = {
            "ORDERBY": "pub_title",
            "START": "0",
            "TYPE": "Publication",
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

        log.info("Parsed publications from url %r. Found %d publications." % (url, len(publication_urls)))

        return publication_urls



class TitleList(ISFDBObject):
    @classmethod
    def url_from_title_and_author(cls, title_tokens, author_tokens):
        title = ' '.join(title_tokens)
        author = ' '.join(author_tokens)

        title = re.sub(r"(.+),? (The|A|An)$", r"\2 \1", title, flags=re.IGNORECASE)

        specialcase = re.match("Sprague Camp", author, flags=re.IGNORECASE)
        if specialcase:
            author = "Sprague de Camp"

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
            "TYPE": "Title",
        }

        return cls.url_from_advanced_search(params)

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


class Publication(ISFDBObject):
    @classmethod
    def url_from_id(cls, isfdb_id):
        return cls.ID_URL % isfdb_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).groups(0)[0]

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        properties = {}
        properties["isfdb"] = cls.id_from_url(url)

        types = {
            "ANTHOLOGY": "Anthology",
            "CHAPBOOK": "Chapbook",
            "COLLECTION": "Collection",
            "ESSAY": "Essay",
            "FANZINE": "Fanzine",
            "MAGAZINE": "Magazine",
            "NONFICTION": "Non-Fiction",
            "NOVEL": "Novel",
            "NOVEL\n [non-genre]": "Novel",
            "OMNIBUS": "Omnibus",
            "POEM": "Poem",
            "SHORTFICTION": "Short Fiction",
            "SHORTFICTION\n [juvenile]": "Juvenile, Short Fiction"
        }

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
                elif section == 'Authors' or section == 'Editors':
                    properties["authors"] = []
                    for a in detail_node.xpath('.//a'):
                        author = a.text_content().strip()
                        if section.startswith('Editors'):
                            properties["authors"].append(author + ' (Editor)')
                        else:
                            properties["authors"].append(author)
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
                    properties["isfdb-title"] = re.search('(\d+)$', title_url).groups(0)[0]
            except Exception as e:
                log.exception('Error parsing section %r for url: %r. Error: %r' % (section, url, e))

        try:
            contents_node = root.xpath('//div[@class="ContentBox"][2]/ul')

            if contents_node:
                properties["comments"] = sanitize_comments_html(tostring(contents_node[0], method='html'))
        except Exception as e:
            log.exception('Error parsing comments for url: %r. Error: %r' % (url, e))

        # Records which are title matched / short fiction
        # examples: http://www.isfdb.org/cgi-bin/title.cgi?725161 , http://www.isfdb.org/cgi-bin/title.cgi?1375155 , http://www.isfdb.org/cgi-bin/title.cgi?414961
        if (not detail_nodes) or (not properties.get("title")):

            try:
                date_text = root.xpath('//div[@class="ContentBox"][contains(., "Publications")]//tr[@class="table1"]/td[2]')[0].text_content().strip()
                # We use this instead of strptime to handle dummy days and months
                # E.g. 1965-00-00
                year, month, day = [int(p) for p in date_text.split("-")]
                month = month or 1
                day = day or 1
                properties["pubdate"] = datetime.datetime(year, month, day)
            except ValueError as e: # Handle titles without a date; example http://www.isfdb.org/cgi-bin/pl.cgi?282252
                log.exception('Error parsing date for url: %r. Error: %r' % (url, e))

            properties["publisher"] = root.xpath('//div[@class="ContentBox"][contains(., "Publications")]//tr[@class="table1"]/td[4]')[0].text_content().strip()

            isbn = root.xpath('//div[@class="ContentBox"][contains(., "Publications")]//tr[@class="table1"]/td[5]')
            if isbn:
                properties["isbn"] = isbn[0].text_content().strip().replace("-", "")

            properties["isfdb-title"] = root.xpath('//div[@class="ContentBox"][1]/span/text()')[0]

            properties["title"] = root.xpath('//div[@class="ContentBox"][1]/b[text()="Title:"]/following-sibling::text()')[0].strip()

            properties["authors"] = []
            # See https://stackoverflow.com/questions/26282186/how-to-find-all-immediately-adjacent-siblings-with-xpath
            for a in root.xpath('//div[@class="ContentBox"][1]/b[contains(text(),"Author")]/following-sibling::*[name()!="a"][1]/preceding-sibling::a'):
                properties["authors"].append(a.text_content().strip())

            properties["tags"] = types[root.xpath('//div[@class="ContentBox"][1]/b[text()="Type:"]/following-sibling::text()')[0].strip()]

            series = root.xpath('//div[@class="ContentBox"][1]/b[text()="Series:"]/following-sibling::text()')
            if series:
                properties["series"] = series[0].strip()

            properties["languages"] = root.xpath('//div[@class="ContentBox"][1]/b[text()="Language:"]/following-sibling::text()')[0].strip()

        try:
            img_src = root.xpath('//div[@id="content"]//table//tr[1]/td[1]/a/img/@src')
            if img_src:
                properties["cover_url"] = img_src[0]
        except Exception as e:
            log.exception('Error parsing cover for url: %r. Error: %r' % (url, e))

        return properties


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
        return root.xpath('//div[@id="main"]/a/img/@src')


# For completeness, make it possible to fetch publications off a title page via title id (although it doesn't seem super useful)
class Title(ISFDBObject):
    pass
