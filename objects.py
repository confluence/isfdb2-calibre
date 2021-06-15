#!/usr/bin/env python3

import re
import datetime

from lxml import etree
from lxml.html import fromstring, tostring
from urllib.parse import urlencode
import codecs

from calibre.utils.cleantext import clean_ascii_chars
from calibre.library.comments import sanitize_comments_html


class ISFDBObject(object):
    @classmethod
    def root_from_url(cls, browser, url, timeout, log):
        # log.info('*** Enter ISFDBObject.root_from_url().')
        # log.info('url={0}'.format(url))
        response = browser.open_novisit(url, timeout=timeout)
        raw = response.read()
        raw = raw.decode('iso_8859_1', 'ignore')  # site encoding is iso-8859-1
        return fromstring(clean_ascii_chars(raw))


class SearchResults(ISFDBObject):
    URL = 'http://www.isfdb.org/cgi-bin/adv_search_results.cgi?';
    TYPE = None;

    @classmethod
    def url_from_params(cls, params, log):
        # log.info("*** Enter SearchResults.url_from_params()")
        # return cls.URL + urlencode(params)  # Default encoding is utf-8, but ISFDB site is on iso-8859-1 (Latin-1)
        # Example original title with german umlaut: "Überfall vom achten Planeten"
        # Default urlencode() encodes:
        # http://www.isfdb.org/cgi-bin/adv_search_results.cgi?ORDERBY=title_title&START=0&TYPE=Title&USE_1=title_title&OPERATOR_1=contains&TERM_1=%C3%9Cberfall+vom+achten+Planeten&USE_2=author_canonical&OPERATOR_2=contains&TERM_2=Staff+Caine&CONJUNCTION_1=AND
        # and leads to "No records found"
        # website has <meta http-equiv="content-type" content="text/html; charset=iso-8859-1">
        # search link should be (encoded by isfdb.org search form itself):
        # isfdb.org: http://www.isfdb.org/cgi-bin/adv_search_results.cgi?USE_1=title_title&O_1=contains&TERM_1=%DCberfall+vom+achten+Planeten&C=AND&USE_2=title_title&O_2=exact&TERM_2=&USE_3=title_title&O_3=exact&TERM_3=&USE_4=title_title&O_4=exact&TERM_4=&USE_5=title_title&O_5=exact&TERM_5=&USE_6=title_title&O_6=exact&TERM_6=&USE_7=title_title&O_7=exact&TERM_7=&USE_8=title_title&O_8=exact&TERM_8=&USE_9=title_title&O_9=exact&TERM_9=&USE_10=title_title&O_10=exact&TERM_10=&ORDERBY=title_title&ACTION=query&START=0&TYPE=Title
        # log.info("urlencode(params, encoding='iso-8859-1')={0}".format(urlencode(params, encoding='iso-8859-1')))
        try:
            return cls.URL + urlencode(params, encoding='iso-8859-1')
        except UnicodeEncodeError as e:
            log.error('Error while encoding {0}: {1}.'.format(params, e))
            encoded_params = urlencode(params, encoding='iso-8859-1', errors='replace')
            encoded_params = encoded_params.split('%3F')[0][:-1]  # cut the search string (? is the encoding replae char)
            return cls.URL + encoded_params

    @classmethod
    def is_type_of(cls, url):
        return url.startswith(cls.URL) and ("TYPE=%s" % cls.TYPE) in url


class PublicationsList(SearchResults):
    TYPE = "Publication"

    @classmethod
    def url_from_isbn(cls, isbn, log):
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

        return cls.url_from_params(params, log)

    @classmethod
    def url_from_title_and_author(cls, title, author, log):

        # log.info("*** Enter PublicationsList.url_from_title_and_author().")
        # log.info("title={0}, author={1}".format(title, author))

        # TODO support adding price or date as a supplementary field
        # but where will it go in the interface?
        # bertholdm: Metadata plugins are not able to write user defined fields.

        field = 0

        params = {
            "ORDERBY": "pub_title",  # "ORDERBY": "pub_year"
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

        return cls.url_from_params(params, log)

    @classmethod
    def from_url(cls, browser, url, timeout, log):

        # log.info('*** Enter PublicationsList.from_url().')
        # log.info('url={0}'.format(url))

        publication_stubs = []

        root = cls.root_from_url(browser, url, timeout, log)

        # Get rid of tooltips
        try:
            for tooltip in root.xpath('//sup[@class="mouseover"]'):
                tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
            for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
                tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        except:
            pass
                
        rows = root.xpath('//div[@id="main"]/table/tr')

        for row in rows:
            # log.info('row={0}'.format(row.xpath('.')[0].text_content()))
            if not row.xpath('td'):
                continue  # header

            publication_stubs.append(Publication.stub_from_search(row, log))

        log.info("Parsed publications from url %r. Found %d publications." % (url, len(publication_stubs)))

        return publication_stubs


class TitleList(SearchResults):
    # TODO: separate permissive title/author search from specific lookup of a publication
    # TODO: isbn not possible; add type to exact search?

    TYPE = "Title"

    @classmethod
    def url_from_exact_title_author_and_type(cls, title, author, ttype, log):
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
            "ORDERBY": "title_title",  # "ORDERBY": "title_copyright",
            "START": "0",
            "TYPE": cls.TYPE,
        }

        return cls.url_from_params(params, log)

    @classmethod
    def url_from_title_and_author(cls, title, author, log):
        field = 0

        params = {
            "ORDERBY": "title_title",  # "ORDERBY": "title_copyright",
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

        if "USE_2" in params:
            params.update({
                "CONJUNCTION_1": "AND",
            })

        return cls.url_from_params(params, log)

    @classmethod
    def from_url(cls, browser, url, timeout, log):

        # log.info('*** Enter TitleList.from_url().')
        # log.info('url={0}'.format(url))

        title_stubs = []

        root = cls.root_from_url(browser, url, timeout, log)  # site encoding is iso-8859-1
        
        # Get rid of tooltips
        try:
            for tooltip in root.xpath('//sup[@class="mouseover"]'):
                tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
            for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
                tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        except:
            pass
        
        rows = root.xpath('//div[@id="main"]/form/table/tr')

        for row in rows:
            # log.info('row={0}'.format(row.xpath('.')[0].text_content()))
            if not row.xpath('td'):
                continue  # header

            title_stubs.append(Title.stub_from_search(row, log))

        log.info("Parsed titles from url %r. Found %d titles." % (url, len(title_stubs)))

        return title_stubs


class Record(ISFDBObject):
    URL = None

    @classmethod
    def is_type_of(cls, url):
        return url.startswith(cls.URL)


class Publication(Record):
    URL = 'http://www.isfdb.org/cgi-bin/pl.cgi?'

    EXTERNAL_IDS = {
        'DNB': ["dnb", "Deutsche Nationalbibliothek", "http://d-nb.info/"],
        'OCLC/WorldCat': ["oclc-worldcat", "Online Computer Library Center", "http://www.worldcat.org/oclc/"],
    }

    BOOK_VARIANT = 0  # Workaround for Calibre's too strict merge method

    @classmethod
    def url_from_id(cls, isfdb_id):
        return cls.URL + isfdb_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def stub_from_search(cls, row, log):
        properties = {}
        properties["title"] = row.xpath('td[1]/a')[0].text_content()
        properties["authors"] = [a.text_content() for a in row.xpath('td[3]/a')]
        properties["url"] = row.xpath('td[1]/a/@href')[0]
        # Display publications in Calibre GUI in ascending order by date
        properties["pub_year"] = row.xpath('td[2]')[0].text_content().strip()[:4]
        return properties

    @classmethod
    def from_url(cls, browser, url, timeout, log):

        # log.info('*** Enter Publication.from_url().')
        # log.info('url={0}'.format(url))

        properties = {}
        properties["isfdb"] = cls.id_from_url(url)

        root = cls.root_from_url(browser, url, timeout, log)

        # Get rid of tooltips
        for tooltip in root.xpath('//sup[@class="mouseover"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it

        # Records with a cover image
        detail_nodes = root.xpath('//div[@id="content"]//td[@class="pubheader"]/ul/li')
        # Records without a cover image
        if not detail_nodes:
            detail_nodes = root.xpath('//div[@id="content"]/div/ul/li')  # no table (on records with no image)

        for detail_node in detail_nodes:
            section = detail_node[0].text_content().strip().rstrip(':')
            if section[:7] == 'Notes: ':  # if accidentally stripped in notes itself
                section = section[:5]

            # log.info('section={0}'.format(section))
            # try:
            #     log.info('text content={0}'.format(detail_node[1].text_content().strip()))
            # except IndexError:
            #     pass

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
                        if author == 'uncredited':
                            author = 'unknown'
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

                elif section == 'Format':
                    properties["format"] = detail_node[0].tail.strip()

                elif section == 'ISBN':
                    properties["isbn"] = detail_node[0].tail.strip('[] \n')

                elif section == 'Publisher':
                    try:
                        properties["publisher"] = detail_node.xpath('a')[0].text_content().strip()
                    except IndexError:
                        properties["publisher"] = detail_node.xpath('div/a')[0].text_content().strip()  # toolötip div

                elif section == 'Pub. Series':
                    # If series is a url, open series page and search for "Sub-series of:"
                    # http://www.isfdb.org/cgi-bin/pe.cgi?45706
                    # Scan series record
                    properties["series"] = ''
                    # if ISFDB.prefs["combine_series"]:
                    # url = detail_node[1].xpath('//a[contains(text(), "' + detail_node[1].text_content().strip() + '")]/@href')  # get all urs
                    series_url = str(detail_node[1].xpath('./@href')[0])
                    # log.info('url={0}'.format(series_url))
                    properties["series"] = Series.from_url(browser, series_url, timeout, log)
                    if properties["series"] == '':
                        properties["series"] = detail_node.xpath('a')[0].text_content().strip()

                elif section == 'Pub. Series #':
                    if '/' in detail_node[0].tail:
                        # Calibre accepts only float format compatible numbers, not e. g. "61/62"
                        series_index_list = detail_node[0].tail.split('/')
                        properties["series_index"] = int("".join(filter(str.isdigit, series_index_list[0])).strip())
                        properties["series_number_notes"] = \
                            _("Reported number was {0} and was reduced to a Calibre compatible format.<br />").\
                                format(detail_node[0].tail)
                    else:
                        properties["series_index"] = int("".join(filter(str.isdigit, detail_node[0].tail)))

                elif section == 'Cover':
                    properties["cover"] = ' '.join([x for x in detail_node.itertext()]).strip().replace('\n', '')
                    properties["cover"] = properties["cover"].replace('  ', ' ')

                elif section == 'Notes':
                    notes_nodes = detail_node.xpath('./div[@class="notes"]/ul')  # /li
                    if notes_nodes:
                        if "notes" not in properties:
                            properties["notes"] = sanitize_comments_html(tostring(notes_nodes[0], method='html'))
                        else:
                            properties["notes"] = properties["notes"] + '<br />' + \
                                                  sanitize_comments_html(tostring(notes_nodes[0], method='html'))
                        # log.info('properties["notes"]={0}'.format(properties["notes"]))

                elif section == 'External IDs':
                    sub_detail_nodes = detail_node.xpath('ul/li')
                    for sub_detail_node in sub_detail_nodes:
                        # log.info(sub_detail_node[0].text_content())  # short catalog name
                        # log.info(sub_detail_node[1].text_content())  # catalog number
                        if sub_detail_node[0].text_content() in cls.EXTERNAL_IDS:
                            properties[cls.EXTERNAL_IDS[sub_detail_node[0].text_content()][0]] = \
                                sub_detail_node[1].text_content()

                elif section == 'Date':
                    date_text = detail_node[0].tail.strip()
                    # We use this instead of strptime to handle dummy days and months
                    # E.g. 1965-00-00
                    year, month, day = [int(p) for p in date_text.split("-")]
                    month = month or 1
                    day = day or 1
                    # Correct datetime result for day = 0: Set hour to 2 UTC
                    # (if not, datetime goes back to the last month and, in january, even to december last year)
                    # ToDo: set hour to publisher's timezone?
                    # properties["pubdate"] = datetime.datetime(year, month, day)
                    properties["pubdate"] = datetime.datetime(year, month, day, 2, 0, 0)

                elif section == 'Catalog ID':
                    properties["isfdb-catalog"] = detail_node[0].tail.strip()

                elif section == 'Container Title':
                    title_url = detail_nodes[9].xpath('a')[0].attrib.get('href')
                    properties["isfdb-title"] = Title.id_from_url(title_url)

            except Exception as e:
                log.exception('Error parsing section %r for url: %r. Error: %r' % (section, url, e))

        try:
            contents_node = root.xpath('//div[@class="ContentBox"][2]/ul')
            if contents_node:
                properties["comments"] = sanitize_comments_html(tostring(contents_node[0], method='html'))
        except Exception as e:
            log.exception('Error parsing comments for url: %r. Error: %r' % (url, e))

        combined_comments = ''
        for k in sorted(properties):
            if k in ['comments', 'notes', 'series_number_notes', 'cover']:
                combined_comments = combined_comments  + properties[k] + '<br />'
        properties["comments"] = combined_comments + _('Source: ') + url

        try:
            img_src = root.xpath('//div[@id="content"]//table/tr[1]/td[1]/a/img/@src')
            if img_src:
                properties["cover_url"] = img_src[0]
        except Exception as e:
            log.exception('Error parsing cover for url: %r. Error: %r' % (url, e))

        # Workaround to avoid merging publications with eeh same title and author(s) by Calibre's default behavior
        Publication.BOOK_VARIANT = Publication.BOOK_VARIANT + 1
        properties['book_variant'] = Publication.BOOK_VARIANT

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
        covers = []
        root = cls.root_from_url(browser, url, timeout, log)

        # Get rid of tooltips
        for tooltip in root.xpath('//sup[@class="mouseover"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it

        covers = root.xpath('//div[@id="main"]/a/img/@src')
        log.info("Parsed covers from url %r. Found %d covers." % (url, len(covers)))
        return covers


class Title(Record):
    # title record -> publication record (1:n)

    URL = 'http://www.isfdb.org/cgi-bin/title.cgi?'

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

    # From the ISFDB Database
    LANGUAGES = {
        'Afrikaans': 'afr',
        'Albanian': 'alb',
        'Ancient Greek': 'grc',
        'Arabic': 'ara',
        'Armenian': 'arm',
        'Azerbaijani': 'aze',
        'Basque': 'baq',
        'Belarusian': 'bel',
        'Bengali': 'ben',
        'Bulgarian': 'bul',
        'Burmese': 'bur',
        'Catalan': 'cat',
        'Chinese': 'chi',
        'Czech': 'cze',
        'Danish': 'dan',
        'Dutch': 'dut',
        'English': 'eng',
        'Esperanto': 'epo',
        'Estonian': 'est',
        'Filipino': 'fil',
        'Finnish': 'fin',
        'French': 'fre',
        'Frisian': 'fry',
        'Galician': 'glg',
        'Georgian': 'geo',
        'German': 'ger',
        'Greek': 'gre',
        'Gujarati': 'guj',
        'Hebrew': 'heb',
        'Hindi': 'hin',
        'Croatian': 'hrv',
        'Hungarian': 'hun',
        'Icelandic': 'ice',
        'Indonesian': 'ind',
        'Irish': 'gle',
        'Italian': 'ita',
        'Japanese': 'jpn',
        'Kazakh': 'kaz',
        'Khmer': 'khm',
        'Kyrgyz': 'kir',
        'Korean': 'kor',
        'Latvian': 'lav',
        'Latin': 'lat',
        'Lithuanian': 'lit',
        'Macedonian': 'mac',
        'Malay': 'may',
        'Malayalam': 'mal',
        'Marathi': 'mar',
        'Mongolian': 'mon',
        'Norwegian': 'nor',
        'Persian': 'per',
        'Polish': 'pol',
        'Portuguese': 'por',
        'Romanian': 'rum',
        'Russian': 'rus',
        'Scottish Gaelic': 'gla',
        'Slovak': 'slo',
        'Slovenian': 'slv',
        'Spanish': 'spa',
        'Serbian': 'srp',
        'Sinhalese': 'sin',
        'Swedish': 'swe',
        'Tajik': 'tgk',
        'Tamil': 'tam',
        'Thai': 'tha',
        'Tibetan': 'tib',
        'Turkish': 'tur',
        'Ukrainian': 'ukr',
        'Urdu': 'urd',
        'Uzbek': 'uzb',
        'Vietnamese': 'vie',
        'Welsh': 'wel',
        'Yiddish': 'yid',
        'Amharic': 'amh',
        'Bosnian': 'bos',
        'Hausa': 'hau',
        'Hawaiian': 'haw',
        'Javanese': 'jav',
        'Judeo-Arabic': 'jrb',
        'Karen': 'kar',
        'Ladino': 'lad',
        'Maltese': 'mlt',
        'Minangkabau': 'min',
        'Nyanja': 'nya',
        'Panjabi': 'pan',
        'Samoan': 'smo',
        'Sindhi': 'snd',
        'Somali': 'som',
        'Sundanese': 'sun',
        'Swahili': 'swa',
        'Tagalog': 'tgl',
        'Tatar': 'tat',
        'Telugu': 'tel',
        'Uighur': 'uig',
        'Sanskrit': 'san',
        'Serbo-Croatian Cyrillic': 'scc',
        'Serbo-Croatian Roman': 'scr',
        'Scots': 'sco',
        'Old English': 'ang',
        'Old French': 'fro',
        'Middle English': 'enm',
        'Middle High German': 'gmh',
        'Yoruba': 'yor',
        'Mayan language': 'myn',
        'Akkadian': 'akk',
        'Sumerian': 'sux',
        'Norwegian (Bokmal)': 'nob',
        'Norwegian (Nynorsk)': 'nno',
        'Asturian/Bable': 'ast',
        'Middle French': 'frm',
        'Low German': 'nds',
        'Nepali': 'nep',
        'Pashto/Pushto': 'pus',
        'Shona': 'sna',
        'Old Norse': 'non',
        'Nilo-Saharan language': 'ssa',
        'Bambara': 'bam',
        'Bantu language': 'bnt',
        'Niger-Kordofanian language': 'nic',
        'Ewe': 'ewe',
        'Igbo': 'ibo',
        'Kamba': 'kam',
        'Kannada': 'kan',
        'Kikuyu/Gikuyu': 'kik',
        'Kurdish': 'kur',
        'Lingala': 'lin',
        'Creole or pidgin, French-based': 'cpf',
        'Central American Indian language': 'cai',
        'Nandi': 'niq',
        'Creole or pidgin, English-based': 'cpe',
        'Tigre': 'tig',
        'Tigrinya': 'tir',
        'Tsonga': 'tso',
        'Tswana': 'tsn',
        'Zulu': 'zul',
        'Acoli': 'ach',
        'Fulah': 'ful',
        'Ganda': 'lug',
        'Kinyarwanda': 'kin',
        'Luo': 'luo',
        'Mandingo': 'man',
        'Oriya': 'ori',
        'Pedi/Sepedi/Northern Sotho': 'nso',
        'South Ndebele': 'nbl',
        'Southern Sotho': 'sot',
        'Standard Moroccan Tamazight': 'zgh',
        'Wolof': 'wol',
        'North Ndebele': 'nde',
        'Montenegrin': 'cnr',
        'Mirandese': 'mwl',
        'Lao': 'lao',
        'South American Indian language': 'sai',
        'Interlingua': 'ina',
        'Guarani': 'grn',
        'Maithili': 'mai',
        'Romance language': 'roa',
        'Klingon': 'tlh',
    }

    @classmethod
    def url_from_id(cls, isfdb_title_id):
        return cls.URL + isfdb_title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def stub_from_search(cls, row, log):
        properties = {}

        if row is None:
            log.error('Title.stub_from_search(): row ist None.')
            return properties

        try:
            # #main > form > table > tbody > tr.table1 > td:nth-child(5)
            properties["title"] = row.xpath('td[5]/a')[0].text_content()
            properties["url"] = row.xpath('td[5]/a/@href')[0]
        except IndexError:
            # Handling Tooltip in div
            # //*[@id="main"]/form/table/tbody/tr[3]/td[5]/div
            properties["title"] = row.xpath('td[5]/div/a/text()')[0]
            properties["url"] = row.xpath('td[5]/div/a/@href')[0]
            # log.info('properties["title"]={0}, properties["url"]={1}.'.format(properties["title"], properties["url"]))

        try:
            properties["authors"] = [a.text_content() for a in row.xpath('td[6]/a')]
        except IndexError:
            # Handling Tooltip in div
            properties["title"] = [a.text_content() for a in row.xpath('td[6]/div/a/text()')]

        return properties

    @classmethod
    def from_url(cls, browser, url, timeout, log):

        # log.info('*** Enter Title.from_url().')
        # log.info('url={0}'.format(url))

        properties = {}
        properties["isfdb-title"] = cls.id_from_url(url)

        root = cls.root_from_url(browser, url, timeout, log)

        # Get rid of tooltips
        for tooltip in root.xpath('//sup[@class="mouseover"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it

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
                        properties["title"] = detail_node[1].text_content().split('?')[0].strip()

                elif section in ('Author', 'Authors', 'Editor', 'Editors'):
                    properties["authors"] = []
                    author_links = [e for e in detail_node if e.tag == 'a']
                    for a in author_links:
                        author = a.text_content().strip()
                        if author == 'uncredited':
                            author = 'unknown'
                        if section.startswith('Editor'):
                            properties["authors"].append(author + ' (Editor)')
                        else:
                            properties["authors"].append(author)

                elif section == 'Type':
                    properties["type"] = detail_node[0].tail.strip()
                    if "tags" not in properties:
                        properties["tags"] = []
                    try:
                        tags = cls.TYPE_TO_TAG[properties["type"]]
                        properties["tags"].extend([t.strip() for t in tags.split(",")])
                    except KeyError:
                        pass

                elif section == 'Length':
                    properties["length"] = detail_node[0].tail.strip()
                    if "tags" not in properties:
                        properties["tags"] = []
                    properties["tags"].append(properties["length"])

                elif section == 'Date':
                    # In a title record, the date points always to the first publishing date (copyright)
                    date_text = detail_node[0].tail.strip()
                    # We use this instead of strptime to handle dummy days and months
                    # E.g. 1965-00-00
                    year, month, day = [int(p) for p in date_text.split("-")]
                    month = month or 1
                    day = day or 1
                    # Correct datetime result for day = 0: Set hour to 2 UTC
                    # (if not, datetime goes back to the last month and, in january, even to december last year)
                    # ToDo: set hour to publisher's timezone?
                    # properties["pubdate"] = datetime.datetime(year, month, day)
                    properties["pubdate"] = datetime.datetime(year, month, day, 2, 0, 0)

                elif section == 'Series':
                    # If series is a url, open series page and search for "Sub-series of:"
                    # http://www.isfdb.org/cgi-bin/pe.cgi?45706
                    # Scan series record
                    properties["series"] = ''
                    # if ISFDB.prefs["combine_series"]:
                    url = str(detail_node[1].xpath('./@href')[0])
                    # log.info('url={0}'.format(url))
                    properties["series"] = Series.from_url(browser, url, timeout, log)
                    if properties["series"] == '':
                        properties["series"] = detail_node[1].text_content().strip()

                elif section == 'Series Number':
                    if '/' in detail_node[0].tail:
                        # Calibre accepts only float format compatible numbers, not e. g. "61/62"
                        series_index_list = detail_node[0].tail.split('/')
                        # properties["series_index"] = float(series_index_list[0].strip())
                        properties["series_index"] = int("".join(filter(str.isdigit, series_index_list[0])).strip())
                        properties["series_number_notes"] = \
                            _("Reported number was {0} and was reduced to a Calibre compatible format.").\
                                format(detail_node[0].tail)
                    else:
                        # properties["series_index"] = float(detail_node[0].tail.strip())
                        properties["series_index"] = int("".join(filter(str.isdigit, detail_node[0].tail)))

                elif section == 'Language':
                    properties["language"] = detail_node[0].tail.strip()
                    # For calibre, the strings must be in the language of the current locale
                    # Both Calibre and ISFDB use ISO 639-2 language codes,
                    # but in the ISFDB web page only the language names are shown
                    try:
                        properties["language"] = cls.LANGUAGES[properties["language"]]
                    except KeyError:
                        pass

                elif section == 'Note':
                    if "notes" not in properties:
                        properties["notes"] = detail_node[0].tail.strip()
                    else:
                        properties["notes"] = properties["notes"] + '<br />' + detail_node[0].tail.strip()

                elif section == 'Variant Title of':
                    if "notes" not in properties:
                        properties["notes"] = detail_node[0].tail.strip()
                    else:
                        properties["notes"] = properties["notes"] + '<br />' + detail_node[0].tail.strip()

                elif section == 'Current Tags':
                    if "tags" not in properties:
                        properties["tags"] = []
                    tag_links = [e for e in detail_node if e.tag == 'a']
                    for a in tag_links:
                        tag = a.text_content().strip()
                        if tag != "Add Tags":
                            properties["tags"].append(tag)

            except Exception as e:
                log.exception('Error parsing section %r for url: %r. Error: %r' % (section, url, e))

        if 'comments' in properties:
            properties["comments"] = properties["comments"] + '<br />' + _('Source: ') + url
        else:
            properties["comments"] = '<br />' + _('Source: ') + url

        publication_links = root.xpath('//a[contains(@href, "/pl.cgi?")]/@href')
        properties["publications"] = [Publication.id_from_url(l) for l in publication_links]

        return properties


class Series(Record):
    URL = 'http://www.isfdb.org/cgi-bin/pe.cgi?'

    @classmethod
    def root_from_url(cls, browser, url, timeout, log):
        # log.info('*** Enter Series.root_from_url().')
        # log.info('url={0}'.format(url))
        response = browser.open_novisit(url, timeout=timeout)
        raw = response.read()
        # Parses an XML document or fragment from a string. Returns the root node (or the result returned by a parser target).
        # To override the default parser with a different parser you can pass it to the parser keyword argument.
        # The base_url keyword argument allows to set the original base URL of the document to support relative Paths
        # when looking up external entities (DTD, XInclude, ...).
        return fromstring(clean_ascii_chars(raw))

    @classmethod
    def url_from_id(cls, title_id):
        return cls.URL + title_id

    @classmethod
    def id_from_url(cls, url):
        return re.search('(\d+)$', url).group(1)

    @classmethod
    def from_url(cls, browser, url, timeout, log):

        # log.info('*** Enter Series.from_url().')
        # log.info('url={0}'.format(url))

        properties = {}
        properties["series"] = ''
        properties["sub_series"] = ''
        series_candidate = ''
        full_series = ''

        root = Series.root_from_url(browser, url, timeout, log)

        # Get rid of tooltips
        for tooltip in root.xpath('//sup[@class="mouseover"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it
        for tooltip in root.xpath('//span[@class="tooltiptext tooltipnarrow tooltipright"]'):
            tooltip.getparent().remove(tooltip)  # We grab the parent of the element to call the remove directly on it

        detail_nodes = root.xpath('//div[@id="content"]/div[@class="ContentBox"][1]/ul/li')
        # log.info('Found {0} detail_nodes.'.format(len(detail_nodes)))
        # Text looks like:
        # Publication Series: TerraPub. Series Record # 1094
        # Webpages: Wikipedia-EN
        # Note: Series run from 1957 until 1968 and counts 555 issues. It was continued by Terra Nova.
        # or:
        # Series: Classic-ZyklusSeries Record # 45706
        # Sub-series of: Ren Dhark Universe
        # or:
        # Series: Krieg zwischen den MilchstraßenSeries Record # 38399
        for detail_node in detail_nodes:
            html_line = detail_node.text_content()
            # log.info('html_line={0}'.format(html_line))
            if 'Sub-series of:' in html_line:  # check for main series, if any
                properties["series"] = html_line.split("Sub-series of:", 1)[1].strip()
                break
        for detail_node in detail_nodes:
            html_line = detail_node.text_content()
            # log.info('html_line={0}'.format(html_line))
            series_captions = ['Publication Series:', 'Series:']
            series_record_captions = ['Pub. Series Record #', 'Series Record #']
            for series_caption in series_captions:
                if series_caption in html_line:
                    series_candidate = html_line.split(series_caption, 1)[1].strip()
                    idx = series_captions.index(series_caption)
                    series_candidate = series_candidate.split(series_record_captions[idx], 1)[0].strip()
                    if properties["series"] != '':
                        properties["sub_series"] = series_candidate
                        break
                    else:
                        properties["series"] = series_candidate
                        break
        full_series = properties["series"]
        if properties["sub_series"] != '':
            full_series = full_series + ' | ' + properties["sub_series"]
        # log.info('full_series={0}'.format(full_series))
        return full_series



class ISFDBWebAPI(object):

    # Not yet in use by ISFDB plugin

    # Ref: http://www.isfdb.org/wiki/index.php/Web_API

    # Publication Lookups
    # At this time there are two ways to retrieve publication data from the ISFDB database: by ISBN (getpub.cgi) and by External ID (getpub_by_ID.cgi). The XML data returned by these two APIs is identical. A license key is not required to use them. A valid query returns an XML payload which includes the following:
    # the Records tag which indicates the number of records found
    # zero or more Publication records containing the metadata for matching ISFDB publication record(s)
    #

    import http.client

    host = "www.isfdb.org"

    # @classmethod
    # def root_from_url(cls, browser, url, timeout, log):
    #     log.info('*** Enter ISFDBWebAPI.root_from_url().')
    #     log.info('url={0}'.format(url))
    #     response = browser.open_novisit(url, timeout=timeout)
    #     raw = response.read()
    #     raw = raw.decode('iso_8859_1', 'ignore')
    #     # .encode(encoding='utf-8',errors='ignore')  # site encoding is iso-8859-1!
    #     # re-encode germans umlauts in a iso-8859-1 page to utf-8
    #     # properties["title"] = row.xpath('td[5]/a')[0].text_content().encode(encoding='UTF-8',errors='ignore')
    #
    #     return fromstring(clean_ascii_chars(raw))

    # getpub.cgi
    # The getpub.cgi API takes an ISBN as its argument. If more than one publication is associated with the requested ISBN, multiple publication records will be returned. If an ISBN-10 is submitted, the API will retrieve and return the data for the requested ISBN as well as for the equivalent ISBN-13 (and vice versa.) The URL for getpub.cgi should appear as follows: http://www.isfdb.org/cgi-bin/rest/getpub.cgi?0439176832
    # getpub_by_ID.cgi
    # The getpub_by_ID.cgi API takes two arguments. The first argument is the External ID type -- see the leftmost column on the Advanced Publication Search by External Identifier page for a list of currently supported External ID types. The second argument is the External ID value.
    # If more than one publication is associated with the requested External ID, multiple publication records will be returned. The URL for getpub_by_ID.cgi should appear as follows: http://www.isfdb.org/cgi-bin/rest/getpub_by_ID.cgi?ASIN+B0764JW7DK
    #
    # Example python script utilizing getpub.cgi

    def GetXml(isbn):
        webservice = httpclient.HTTPConnection(host)
        command = '/cgi-bin/rest/getpub.cgi?%s' % isbn
        webservice.putrequest("GET", command)
        webservice.putheader("Host", host)
        webservice.putheader("User-Agent", "Wget/1.9+cvs-stable (Red Hat modified)")
        webservice.endheaders()
        errcode, errmsg, headers = webservice.getreply()
        if errcode != 200:
            resp = webservice.getfile()
            print
            "Error:", errmsg
            print
            "Resp:", resp.read()
            resp.close()
            return ''
        else:
            resp = webservice.getfile()
            raw = resp.read()
            resp.close()
            index = raw.find('<?xml')
            return raw[index:]

        # Error Conditions
        # If no matching publication records are found, getpub.cgi and getpub_by_ID.cgi will return an XML structure with the number of records set to zero:
        #
        # <?xml version="1.0" encoding="iso-8859-1" ?>
        # <ISFDB>
        #   <Records>0</Records>
        #   <Publications>
        #   </Publications>
        # </ISFDB>

        # <?xml version="1.0" encoding="iso-8859-1" ?>
        # <ISFDB>
        #  <Records>1</Records>
        #  <Publications>
        #    <Publication>
        #      <Record>325837</Record>
        #      <Title>The Winchester Horror</Title>
        #      <Authors>
        #        <Author>William F. Nolan</Author>
        #      </Authors>
        #      <Year>1998-00-00</Year>
        #      <Isbn>1881475530</Isbn>
        #      <Publisher>Cemetery Dance Publications</Publisher>
        #      <PubSeries>Cemetery Dance Novella</PubSeries>
        #      <PubSeriesNum>6</PubSeriesNum>
        #      <Price>$30.00</Price>
        #      <Pages>111</Pages>
        #      <Binding>hc</Binding>
        #      <Type>CHAPBOOK</Type>
        #      <Tag>THWNCHSTRH1998</Tag>
        #      <CoverArtists>
        #        <Artist>Eric Powell</Artist>
        #      </CoverArtists>
        #      <Note>Hardcover Limited Edition of 450 signed and numbered copies bound in full-cloth and Smyth sewn</Note>
        #      <External_IDs>
        #        <External_ID>
        #           <IDtype>1</IDtype>
        #           <IDtypeName>ASIN</IDtypeName>
        #           <IDvalue>B01G1K1RV8</IDvalue>
        #        </External_ID>
        #      </External_IDs>
        #    </Publication>
        #  </Publications>
        # </ISFDB>
