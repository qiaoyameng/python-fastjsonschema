"""
Optional compile-time source map.

Maps line ranges of the generated Python validation code back to the schema
node they were generated from: the schema resource URI, the JSON Pointer
(RFC 6901) inside that resource and the keyword (rule) being validated.

The map is pure data. It is serialized as JSON, so saving and loading it
never executes any code and never depends on the current working directory.
"""

import json
from typing import Any, NamedTuple


class SourceLocation(NamedTuple):
    """
    Position of a schema node a generated code range was produced from.

    ``uri`` is the (absolute) URI of the schema resource -- it changes when
    a nested ``$id`` introduces a new resource. ``pointer`` is the JSON
    Pointer into that resource with RFC 6901 escaping (``~0`` for ``~`` and
    ``~1`` for ``/``); non-ASCII characters are kept as-is. ``rule`` is the
    schema keyword the generated lines validate (e.g. ``minimum``,
    ``properties``) or ``$ref`` for lines calling a referenced schema.
    """

    uri: str
    pointer: str
    rule: 'str | None'


def escape_pointer_segment(segment: Any) -> str:
    """
    Escape a single JSON Pointer segment according to RFC 6901.
    """
    return str(segment).replace('~', '~0').replace('/', '~1')


class SourceMap:
    """
    Mapping between generated code lines and schema locations.

    Lines are 1-based and inclusive, relative to the code text the map was
    created for: for :any:`fastjsonschema.compile` that is the generated
    function body (what tracebacks of the in-memory compiled function
    report), for :any:`fastjsonschema.compile_to_code` it is the whole
    returned code string.
    """

    VERSION = 1

    def __init__(self, entries=()):
        # entries: iterable of (start_line, end_line, SourceLocation)
        self._entries = tuple(entries)

    @property
    def entries(self):
        """
        Tuple of ``(start_line, end_line, SourceLocation)`` ranges.
        """
        return self._entries

    def locate(self, line: int) -> 'SourceLocation | None':
        """
        Return the schema location for a generated code line, if any.
        """
        for start, end, location in self._entries:
            if start <= line <= end:
                return location
        return None

    def locations_for_traceback(self, tb) -> 'list[SourceLocation]':
        """
        Map a traceback to schema locations, outermost call first.

        Only frames of generated validation functions are considered. The
        last item is the location of the rule that failed; the items before
        it describe the reference path (``$ref`` call sites) taken to get
        there, which is essential when one generated function is shared by
        several ``$ref`` entries.
        """
        locations = []
        while tb is not None:
            if tb.tb_frame.f_code.co_name.startswith('validate'):
                location = self.locate(tb.tb_lineno)
                if location is not None:
                    locations.append(location)
            tb = tb.tb_next
        return locations

    def format_traceback(self, tb) -> str:
        """
        Render :any:`locations_for_traceback` as human readable lines.
        """
        lines = []
        for location in self.locations_for_traceback(tb):
            suffix = ' (rule: {})'.format(location.rule) if location.rule else ''
            lines.append('{}#{}{}'.format(location.uri, location.pointer, suffix))
        return '\n'.join(lines)

    def shifted(self, offset: int) -> 'SourceMap':
        """
        Return a copy with all line numbers moved by ``offset``.
        """
        return SourceMap(
            (start + offset, end + offset, location)
            for start, end, location in self._entries
        )

    def to_dict(self) -> dict:
        return {
            'version': self.VERSION,
            'entries': [
                {
                    'start': start,
                    'end': end,
                    'uri': location.uri,
                    'pointer': location.pointer,
                    'rule': location.rule,
                }
                for start, end, location in self._entries
            ],
        }

    def to_json(self, **kwargs) -> str:
        """
        Serialize to a JSON string. Keyword arguments are passed to
        :func:`json.dumps`; ``ensure_ascii`` defaults to ``False`` so
        Unicode property names stay readable.
        """
        kwargs.setdefault('ensure_ascii', False)
        kwargs.setdefault('indent', 2)
        return json.dumps(self.to_dict(), **kwargs)

    def save(self, file) -> None:
        """
        Save the map as JSON. ``file`` is a path or a writable file object.
        """
        if hasattr(file, 'write'):
            file.write(self.to_json())
            return
        with open(file, 'w', encoding='utf-8') as map_file:
            map_file.write(self.to_json())

    @classmethod
    def from_dict(cls, data: dict) -> 'SourceMap':
        if data.get('version') != cls.VERSION:
            raise ValueError('Unsupported source map version: {!r}'.format(data.get('version')))
        entries = [
            (
                item['start'],
                item['end'],
                SourceLocation(item['uri'], item['pointer'], item.get('rule')),
            )
            for item in data['entries']
        ]
        return cls(entries)

    @classmethod
    def from_json(cls, text: str) -> 'SourceMap':
        """
        Load a map from a JSON string. Only JSON is parsed, never code.
        """
        return cls.from_dict(json.loads(text))

    @classmethod
    def load(cls, file) -> 'SourceMap':
        """
        Load a map saved with :any:`save`. ``file`` is a path or a readable
        file object.
        """
        if hasattr(file, 'read'):
            return cls.from_json(file.read())
        with open(file, encoding='utf-8') as map_file:
            return cls.from_json(map_file.read())

    def __eq__(self, other):
        return isinstance(other, SourceMap) and self._entries == other._entries

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return 'SourceMap({} entries)'.format(len(self._entries))
