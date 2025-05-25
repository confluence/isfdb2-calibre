#!/usr/bin/env python3

import re
import datetime

from lxml.html import fromstring, tostring
from urllib.parse import urlencode
import codecs

from calibre.utils.cleantext import clean_ascii_chars
from calibre.library.comments import sanitize_comments_html


def get_first(root, path):
    results = root.xpath(path)
    return results[0] if results else None


class ISFDBObject(object):
    @classmethod
    def root_from_url(cls, browser, url, timeout, log):
        response = browser.open_novisit(url, timeout=timeout)
        raw = response.read()
        return fromstring(clean_ascii_chars(raw))


class SearchResults(ISFDBObject):
    URL = 'https://www.isfdb.org/cgi-bin/adv_search_results.cgi?';
    TYPE = None;

    @classmethod
    def url_from_params(cls, params):
        return cls.URL + urlencode(params, encoding="iso-8859-1")

    @classmethod
    def is_type_of(cls, url):
        return url.startswith(cls.URL) and ("TYPE=%s" % cls.TYPE) in url


class PublicationsList(SearchResults):
    TYPE = "Publication"

    @classmethod
    def _url_from(cls, params, field, month, year, price):
        if month:
            field += 1
            params.update({
                "USE_%d" % field: "pub_month",
                "OPERATOR_%d" % field: "exact",
                "TERM_%d" % field: month,
            })
        elif year:
            field += 1
            params.update({
                "USE_%d" % field: "pub_year",
                "OPERATOR_%d" % field: "exact",
                "TERM_%d" % field: year,
            })

        if price:
            field += 1
            params.update({
                "USE_%d" % field: "pub_price",
                "OPERATOR_%d" % field: "exact",
                "TERM_%d" % field: price,
            })

        for i in range(1, field):
            params.update({
                "CONJUNCTION_%d" % i: "AND",
            })

        params.update({
            "ORDERBY": "pub_title",
            "START": "0",
            "TYPE": cls.TYPE,
        })

        return cls.url_from_params(params)

    @classmethod
    def url_from_isbn(cls, isbn, month, year, price):
        params = {
            "USE_1": "pub_isbn",
            "OPERATOR_1": "exact",
            "TERM_1": isbn,
        }

        return cls._url_from(params, 1, month, year, price)

    @classmethod
    def url_from_catalog_id(cls, catalog_id, month, year, price):
        params = {
            "USE_1": "pub_catalog",
            "OPERATOR_1": "exact",
            "TERM_1": catalog_id,
        }

        return cls._url_from(params, 1, month, year, price)

    @classmethod
    def url_from_title_and_author(cls, title, author, month, year, price):
        field = 0

        params = {}

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

        return cls._url_from(params, field, month, year, price)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        publication_stubs = []

        root = cls.root_from_url(browser, url, timeout, log)
        rows = root.xpath('//div[@id="main"]/table/tr')

        for row in rows:
            if not row.xpath('td'):
                continue # header

            publication_stubs.append(Publication.stub_from_search(row))

        log.info("Parsed publications from url %r. Found %d publications." % (url, len(publication_stubs)))

        return publication_stubs



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
    def url_from_title_and_author(cls, title, author, month, year):
        field = 0

        params = {
            "ORDERBY": "title_title",
            "START": "0",
            "TYPE": cls.TYPE,
        }

        if title:
            field += 1
            params.update({
                "USE_%d" % field: "title_title",
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

        if month:
            field += 1
            params.update({
                "USE_%d" % field: "month",
                "OPERATOR_%d" % field: "exact",
                "TERM_%d" % field: month,
            })
        elif year:
            field += 1
            params.update({
                "USE_%d" % field: "title_copyright",
                "OPERATOR_%d" % field: "exact",
                "TERM_%d" % field: year,
            })

        for i in range(1, field):
            params.update({
                "CONJUNCTION_%d" % i: "AND",
            })

        return cls.url_from_params(params)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        title_stubs = []

        root = cls.root_from_url(browser, url, timeout, log)
        rows = root.xpath('//div[@id="main"]/form/table/tr')

        for row in rows:
            if not row.xpath('td'):
                continue # header

            title_stubs.append(Title.stub_from_search(row))

        log.info("Parsed titles from url %r. Found %d titles." % (url, len(title_stubs)))

        return title_stubs


class Record(ISFDBObject):
    URL = None

    @classmethod
    def is_type_of(cls, url):
        return url.startswith(cls.URL)


class Publication(Record):
    URL = 'https://www.isfdb.org/cgi-bin/pl.cgi?'

    @classmethod
    def url_from_id(cls, isfdb_id):
        return cls.URL + isfdb_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def stub_from_search(cls, row):
        properties = {}
        properties["title"] = get_first(row, 'td[1]/a').text_content()
        properties["authors"] = [a.text_content() for a in row.xpath('td[3]/a')]
        properties["url"] = get_first(row, 'td[1]/a/@href')
        return properties

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
                    properties["publisher"] = get_first(detail_node, 'a').text_content().strip()
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

            except Exception as e:
                log.exception('Error parsing section %r for url: %r. Error: %r' % (section, url, e) )

        try:
            # This should always exist
            contents_box = get_first(root, '//div[@class="ContentBox"][2]')

            # If this is an anthology or collection
            title_link = get_first(contents_box, 'span[@class="containertitle"]/following-sibling::a[contains(@href, "title.cgi")]')
            # If this is a novel
            if title_link is None:
                title_link = get_first(contents_box, './/li[contains(., "novel by")]//a[contains(@href, "title.cgi")]')
            if title_link is not None:
                properties["isfdb-title"] = Title.id_from_url(title_link.get("href"))

            # Strip listing link from contents title
            listing_link = get_first(contents_box, './/a[@class="listingtext"]')
            if listing_link is not None:
                listing_link.getparent().remove(listing_link)

            # Strip tooltips from contents
            for e in contents_box.xpath('.//sup[@class="mouseover"]'):
                e.getparent().remove(e)
            for e in contents_box.xpath('.//span[contains(@class, "tooltiptext")]'):
                e.getparent().remove(e)

            properties["comments"] = sanitize_comments_html(tostring(contents_box, method='html'))
        except Exception as e:
            log.exception('Error parsing comments for url: %r. Error: %r' % (url, e))

        try:
            img_src = get_first(root, '//div[@id="content"]//table/tr[1]/td[1]/a/img/@src')
            if img_src is not None:
                properties["cover_url"] = img_src
        except Exception as e:
            log.exception('Error parsing cover for url: %r. Error: %r' % (url, e))

        return properties


class TitleCovers(Record):
    URL = 'https://www.isfdb.org/cgi-bin/titlecovers.cgi?'

    @classmethod
    def url_from_id(cls, title_id):
        return cls.URL + title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        covers = []
        root = cls.root_from_url(browser, url, timeout, log)
        covers = root.xpath('//div[@id="main"]/a/img/@src')
        log.info("Parsed covers from url %r. Found %d covers." % (url, len(covers)))
        return covers

class Title(Record):
    URL = 'https://www.isfdb.org/cgi-bin/title.cgi?'

    TYPE_TO_TAG = {
            "ANTHOLOGY": "anthology",
            "CHAPBOOK": "chapbook",
            "COLLECTION": "collection",
            "ESSAY": "essay",
            "FANZINE": "fanzine",
            "MAGAZINE": "magazine",
            "NONFICTION": "non-fiction",
            "NOVEL": "novel",
            "NOVEL\n [non-genre]": "novel",
            "OMNIBUS": "omnibus",
            "POEM": "poem",
            "SERIAL": "serial",
            "SHORTFICTION": "short fiction",
            "SHORTFICTION\n [juvenile]": "juvenile, short fiction",
            "SHORTFICTION\n [non-genre]": "short fiction"
        }

    @classmethod
    def url_from_id(cls, isfdb_title_id):
        return cls.URL + isfdb_title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def stub_from_search(cls, row):
        properties = {}
        properties["title"] = get_first(row, 'td[5]/a').text_content()
        properties["authors"] = [a.text_content() for a in row.xpath('td[6]/a')]
        properties["url"] = get_first(row, 'td[5]/a/@href')
        return properties

    @classmethod
    def from_url(cls, browser, url, timeout, log):
        properties = {}
        properties["isfdb-title"] = cls.id_from_url(url)

        root = cls.root_from_url(browser, url, timeout, log)

        detail_div = get_first(root, '//div[@class="ContentBox"]')

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
                    if "tags" not in properties:
                        properties["tags"] = []
                    tags = cls.TYPE_TO_TAG[properties["type"]]
                    properties["tags"].extend([t.strip() for t in tags.split(",")])
                elif section == 'Length':
                    properties["length"] = detail_node[0].tail.strip()
                    if "tags" not in properties:
                        properties["tags"] = []
                    properties["tags"].append(properties["length"])
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
                    if "tags" not in properties:
                        properties["tags"] = []
                    tag_links = [e for e in detail_node if e.tag == 'a']
                    for a in tag_links:
                        tag = a.text_content().strip()
                        if tag != "Add Tags":
                            properties["tags"].append(tag)

            except Exception as e:
                log.exception('Error parsing section %r for url: %r. Error: %r' % (section, url, e) )

        publication_links = root.xpath('//a[contains(@href, "/pl.cgi?")]/@href')
        properties["publications"] = [Publication.id_from_url(l) for l in publication_links]

        return properties
