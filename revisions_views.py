# -*- coding: UTF-8 -*-
# Copyright (C) 2009 Sylvain Taverne <sylvain@itaapy.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

# Import from standard library
from operator import itemgetter
from re import compile, sub
from subprocess import CalledProcessError

# Import from itools
from itools.core import thingy_property, thingy_lazy_property
from itools.core import OrderedDict
from itools.datatypes import Boolean, String
from itools.gettext import MSG
from itools.stl import make_stl_template
from itools.uri import encode_query, get_reference
from itools.web import stl_view, hidden_field

# Import from ikaaro
from buttons import Button
from views import Container_Search, Container_Sort, Container_Batch
from views import Container_Form, Container_Table


def get_colored_diff(diff):
    """Turn a diff source into a namespace for HTML display"""
    changes = []
    password_re = compile('<password>(.*)</password>')
    # The anchor index to link from the diff stat
    link_index = -1
    for line in diff.splitlines():
        if line[:5] == 'index' or line[:3] in ('---', '+++', '@@ '):
            continue
        css = None
        is_header = (line[:4] == 'diff')
        if is_header:
            link_index += 1
        elif line:
            # For security, hide password the of metadata files
            line = sub(password_re, '<password>***</password>', line)
            if line[0] == '-':
                css = 'rem'
            elif line[0] == '+':
                css = 'add'
        # Add the line
        changes.append({'css': css, 'value': line, 'is_header': is_header,
            'index': link_index})
    return changes



def get_colored_stat(stat):
    """Turn a diff stat into a namespace for HTML display"""
    table = []
    for line in stat.splitlines():
        if '|' in line:
            # File change
            filename, change = [x.strip() for x in line.split('|')]
            nlines, change = change.split(' ', 1)
            if '->' in change:
                # Binary change
                before, after = change.split('->')
            else:
                # Text change
                before = change.strip('+')
                after = change.strip('-')
            table.append({'value': filename, 'nlines': nlines,
                'before': before, 'after': after})
        else:
            # Last line of summary
            summary = line
    namespace = {}
    namespace['table'] = table
    namespace['summary'] = summary
    return namespace



def get_older_state(resource, revision, context):
    """All-in-one to get an older metadata and handler state."""
    # Heuristic to remove the database prefix
    prefix = len(str(context.server.target)) + len('/database/')
    # Metadata
    path = str(resource.metadata.uri)[prefix:]
    metadata = context.database.get_blob(revision, path)
    # Handler
    path = str(resource.handler.uri)[prefix:]
    try:
        handler = context.database.get_blob(revision, path)
    except CalledProcessError:
        # Phantom handler or renamed file
        handler = ''
    return metadata, handler



class IndexRevision(String):

    @staticmethod
    def decode(data):
        index, revision = data.split('_')
        return int(index), revision


    @staticmethod
    def encode(value):
        raise NotImplementedError



class DiffButton(Button):
    access = 'is_allowed_to_edit'
    name = 'diff'
    title = MSG(u"Diff between selected revisions")
    css = 'button-compare'



class DBResource_CommitLog(stl_view):

    access = 'is_allowed_to_edit'
    view_title = MSG(u"Commit Log")

    template = make_stl_template("${batch}${form}")

    ids = hidden_field(source='query', multiple=True, required=True)
    ids.datatype = IndexRevision


    # Search
    @thingy_lazy_property
    def items(self):
        view = self.view
        items = view.resource.get_revisions(content=True)
        for i, item in enumerate(items):
            item['username'] = view.context.get_user_title(item['username'])
            # Hint to sort revisions quickly
            item['index'] = i
        return items

    search = Container_Search()
    search.items = items

    # Sort
    @thingy_lazy_property
    def items(self):
        sort_by = self.sort_by.value
        reverse = self.reverse.value

        # (FIXME) Do not give a traceback if 'sort_by' has an unexpected value
        if sort_by not in self.sort_by.values:
            sort_by = self.sort_by.default

        # Sort & batch
        key = itemgetter(sort_by)
        return sorted(self.view.search.items, key=key, reverse=reverse)

    sort = Container_Sort()
    sort.sort_by = sort.sort_by(value='date')
    sort.sort_by.values = OrderedDict([
        ('date', {'title': MSG(u'Last Change')}),
        ('username', {'title': MSG(u'Author')}),
        ('message', {'title': MSG(u'Comment')})])
    sort.reverse = sort.reverse(value=True)
    sort.items = items

    # Batch
    @thingy_lazy_property
    def items(self):
        start = self.batch_start.value
        size = self.batch_size.value
        return self.view.sort.items[start:start+size]

    batch = Container_Batch()
    batch.items = items

    # Form
    form = Container_Form()
    form.actions = [DiffButton]

    # Form content
    @thingy_property
    def header(self):
        columns = [('checkbox', None, False)]
        for name, value in self.root_view.sort.sort_by.values.items():
            columns.append((name, value['title'], True))
        return columns

    form.content = Container_Table()
    form.content.header = header


    def get_item_value(self, item, column):
        if column == 'checkbox':
            return ('%s_%s' % (item['index'], item['revision']), False)
        elif column == 'date':
            return (item['date'], './;changes?revision=%s' % item['revision'])
        return item[column]


    def action_diff(self):
        # Take newer and older revisions, even if many selected
        ids = sorted(self.ids.value)
        revision = ids.pop()[1]
        to = ids and ids.pop(0)[1] or 'HEAD'
        # FIXME same hack than rename to call a GET from a POST
        query = encode_query({'revision': revision, 'to': to})
        uri = '%s/;changes?%s' % (context.get_link(resource), query)
        return get_reference(uri)



class DBResource_Changes(stl_view):

    access = 'is_admin'
    view_title = MSG(u'Changes')
    template = 'revisions/changes.xml'


    revision = hidden_field(source='query', required=True)
    to = hidden_field(source='query')


    @thingy_lazy_property
    def diff(self):
        revision = self.revision.value
        return self.context.database.get_diff(revision)


    def metadata(self):
        if self.to.value is None:
            metadata = self.diff
            author_name = metadata['author_name']
            metadata['author_name'] = self.context.get_user_title(author_name)
            return metadata

        return None


    def stat(self):
        revision = self.revision.value
        to = self.to.value
        if to is None:
            to = '%s^' % revision
        stat = self.context.database.get_diff_between(revision, to, stat=True)
        return get_colored_stat(stat)


    def changes(self):
        to = self.to.value
        if to is None:
            diff = self.diff['diff']
        else:
            revision = self.revision.value
            diff = self.context.database.get_diff_between(revision, to)

        return get_colored_diff(diff)

