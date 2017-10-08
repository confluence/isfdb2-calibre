#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '''(c) 2017 Adrianna Pińska <adrianna.pinska@gmail.com>,
Xtina Schelin <xtina.schelin@gmail.com>,
Grant Drake <grant.drake@gmail.com>'''
__docformat__ = 'restructuredtext en'

try:
    from PyQt5 import Qt as QtGui
except ImportError:
    from PyQt4 import QtGui
try:
    from PyQt5.Qt import QLabel, QGridLayout, Qt, QGroupBox, QCheckBox
except ImportError:
    from PyQt4.Qt import QLabel, QGridLayout, Qt, QGroupBox, QCheckBox
from calibre.gui2.metadata.config import ConfigWidget as DefaultConfigWidget
from calibre.utils.config import JSONConfig

STORE_NAME = 'Options'
KEY_MAX_DOWNLOADS = 'maxDownloads'
KEY_APPEND_CONTENTS = 'appendContents'

DEFAULT_STORE_VALUES = {
    KEY_MAX_DOWNLOADS: 1,
    KEY_APPEND_CONTENTS: False
}

# This is where all preferences for this plugin will be stored.
plugin_prefs = JSONConfig('plugins/ISFDB2')

# Set defaults.
plugin_prefs.defaults[STORE_NAME] = DEFAULT_STORE_VALUES

class ConfigWidget(DefaultConfigWidget):
    def __init__(self, plugin):
        DefaultConfigWidget.__init__(self, plugin)
        c = plugin_prefs[STORE_NAME]

        other_group_box = QGroupBox('Other options', self)
        self.l.addWidget(other_group_box, self.l.rowCount(), 0, 1, 2)
        other_group_box_layout = QGridLayout()
        other_group_box.setLayout(other_group_box_layout)

        # Maximum # of title/author searches to review.
        max_label = QLabel('Maximum number of search matches to evaluate:', self)
        max_label.setToolTip('''This value will take effect during author / title searches.''')
        other_group_box_layout.addWidget(max_label, 0, 0, 1, 1)
        self.max_downloads_spin = QtGui.QSpinBox(self)
        self.max_downloads_spin.setMinimum(1)
        self.max_downloads_spin.setMaximum(5)
        self.max_downloads_spin.setProperty('value', c.get(KEY_MAX_DOWNLOADS, DEFAULT_STORE_VALUES[KEY_MAX_DOWNLOADS]))
        other_group_box_layout.addWidget(self.max_downloads_spin, 0, 1, 1, 1)
        other_group_box_layout.setColumnStretch(2, 1)

        # Contents field, if possible.
        self.contents_checkbox = QCheckBox('Append contents section to book comments:', self)
        self.contents_checkbox.setToolTip('''Choosing this option will write the contents section to the comments
field, if such a section exists, as is often the case for short story collections and anthologies.''')
        self.contents_checkbox.setChecked(c.get(KEY_APPEND_CONTENTS, DEFAULT_STORE_VALUES[KEY_APPEND_CONTENTS]))
        other_group_box_layout.addWidget(self.contents_checkbox, 2, 0, 1, 3)

    def commit(self):
        DefaultConfigWidget.commit(self)
        new_prefs = {}
        new_prefs[KEY_MAX_DOWNLOADS] = int(unicode(self.max_downloads_spin.value()))
        new_prefs[KEY_APPEND_CONTENTS] = self.contents_checkbox.checkState() == Qt.Checked
        plugin_prefs[STORE_NAME] = new_prefs
