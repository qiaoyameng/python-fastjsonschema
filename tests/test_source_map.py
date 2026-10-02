import json

import pytest

import fastjsonschema
from fastjsonschema import JsonSchemaValueException, SourceLocation, SourceMap


COMMON_URI = 'https://schemas.example.com/common.json'
ROOT_URI = 'https://schemas.example.com/root.json'

REMOTE_SCHEMAS = {
    COMMON_URI: {
        '$id': COMMON_URI,
        'definitions': {
            'weird': {
                'type': 'object',
                'properties': {
                    'a/b': {'type': 'integer'},
                    'c~d': {'type': 'string'},
                    'clé': {'type': 'integer', 'minimum': 5},
                },
                'required': ['a/b', 'c~d', 'clé'],
            },
        },
    },
}

HANDLERS = {'https': lambda uri: REMOTE_SCHEMAS[uri]}

SCHEMA = {
    '$id': ROOT_URI,
    'type': 'object',
    'properties': {
        'thing': {'$ref': COMMON_URI + '#/definitions/weird'},
    },
}

REF_LOCATION = SourceLocation(ROOT_URI, '/properties/thing', '$ref')


def make_valid_thing(**overrides):
    thing = {'a/b': 1, 'c~d': 'x', 'clé': 7}
    thing.update(overrides)
    return thing


@pytest.mark.parametrize('bad_value, pointer, rule', [
    ({'a/b': 'not-an-integer'}, '/definitions/weird/properties/a~1b', 'type'),
    ({'c~d': 42}, '/definitions/weird/properties/c~0d', 'type'),
    ({'clé': 3}, '/definitions/weird/properties/clé', 'minimum'),
])
def test_compile_source_map_remote_ref_escaped_names(bad_value, pointer, rule):
    validate, source_map = fastjsonschema.compile(SCHEMA, handlers=HANDLERS, source_map=True)
    with pytest.raises(JsonSchemaValueException) as exc_info:
        validate({'thing': make_valid_thing(**bad_value)})

    locations = source_map.locations_for_traceback(exc_info.tb)
    # The failing rule definition inside the remote schema resource.
    assert locations[-1] == SourceLocation(COMMON_URI, pointer, rule)
    # The reference path taken to get there.
    assert locations[0] == REF_LOCATION


def test_compile_to_code_source_map_matches_in_memory(tmp_path, monkeypatch):
    code, code_map = fastjsonschema.compile_to_code(SCHEMA, handlers=HANDLERS, source_map=True)
    validate, memory_map = fastjsonschema.compile(SCHEMA, handlers=HANDLERS, source_map=True)

    map_file = tmp_path / 'schema_sm.map.json'
    code_map.save(map_file)
    loaded_map = SourceMap.load(map_file)
    assert loaded_map == code_map

    (tmp_path / 'schema_sm.py').write_text(code, encoding='utf-8')
    with monkeypatch.context() as m:
        m.syspath_prepend(tmp_path)
        import schema_sm
    exported_validate = next(
        value for key, value in vars(schema_sm).items() if key.startswith('validate')
    )

    data = {'thing': make_valid_thing(**{'clé': 3})}
    with pytest.raises(JsonSchemaValueException) as exported_exc:
        exported_validate(data)
    with pytest.raises(JsonSchemaValueException) as memory_exc:
        validate(data)

    expected = SourceLocation(COMMON_URI, '/definitions/weird/properties/clé', 'minimum')
    # Both the exported file run and the in-memory run locate the same node.
    assert loaded_map.locations_for_traceback(exported_exc.tb) == [REF_LOCATION, expected]
    assert memory_map.locations_for_traceback(memory_exc.tb) == [REF_LOCATION, expected]


def test_source_map_shared_ref_keeps_entry_path():
    schema = {
        '$id': ROOT_URI,
        'properties': {
            'first': {'$ref': COMMON_URI + '#/definitions/weird'},
            'second': {'$ref': COMMON_URI + '#/definitions/weird'},
        },
    }
    validate, source_map = fastjsonschema.compile(schema, handlers=HANDLERS, source_map=True)

    definition_location = SourceLocation(COMMON_URI, '/definitions/weird/properties/clé', 'minimum')
    for entry in ('first', 'second'):
        data = {entry: make_valid_thing(**{'clé': 3})}
        with pytest.raises(JsonSchemaValueException) as exc_info:
            validate(data)
        locations = source_map.locations_for_traceback(exc_info.tb)
        # The shared generated function points to the same rule definition...
        assert locations[-1] == definition_location
        # ...while the reference path identifies the entry used this time.
        assert locations[0] == SourceLocation(ROOT_URI, '/properties/' + entry, '$ref')


def test_source_map_nested_id_inline():
    schema = {
        '$id': ROOT_URI,
        'properties': {
            's': {
                '$id': 'sub.json',
                'type': 'object',
                'properties': {'x': {'type': 'integer'}},
            },
        },
    }
    validate, source_map = fastjsonschema.compile(schema, source_map=True)
    with pytest.raises(JsonSchemaValueException) as exc_info:
        validate({'s': {'x': 'not-an-integer'}})
    locations = source_map.locations_for_traceback(exc_info.tb)
    assert locations[-1] == SourceLocation(
        'https://schemas.example.com/sub.json', '/properties/x', 'type',
    )


def test_source_map_nested_id_behind_ref():
    schema = {
        '$id': ROOT_URI,
        'definitions': {
            'sub': {
                '$id': 'sub.json',
                'type': 'object',
                'properties': {'x': {'type': 'integer'}},
            },
        },
        'properties': {'s': {'$ref': 'sub.json'}},
    }
    validate, source_map = fastjsonschema.compile(schema, source_map=True)
    with pytest.raises(JsonSchemaValueException) as exc_info:
        validate({'s': {'x': 'not-an-integer'}})
    locations = source_map.locations_for_traceback(exc_info.tb)
    assert locations == [
        SourceLocation(ROOT_URI, '/properties/s', '$ref'),
        SourceLocation('https://schemas.example.com/sub.json', '/properties/x', 'type'),
    ]


def test_source_map_composition_branches():
    validate, source_map = fastjsonschema.compile(
        {'allOf': [{'type': 'integer'}, {'minimum': 10}]},
        source_map=True,
    )
    with pytest.raises(JsonSchemaValueException) as exc_info:
        validate(5)
    locations = source_map.locations_for_traceback(exc_info.tb)
    assert locations[-1] == SourceLocation('', '/allOf/1', 'minimum')

    validate, source_map = fastjsonschema.compile(
        {'anyOf': [{'type': 'string'}, {'type': 'integer', 'minimum': 10}]},
        source_map=True,
    )
    with pytest.raises(JsonSchemaValueException) as exc_info:
        validate(5)
    locations = source_map.locations_for_traceback(exc_info.tb)
    assert locations[-1] == SourceLocation('', '', 'anyOf')


def test_source_map_save_load_roundtrip(tmp_path, monkeypatch):
    _, source_map = fastjsonschema.compile(SCHEMA, handlers=HANDLERS, source_map=True)
    map_file = tmp_path / 'roundtrip.map.json'
    source_map.save(map_file)

    # The map is plain JSON: loading parses data only, never code.
    text = map_file.read_text(encoding='utf-8')
    assert json.loads(text)['version'] == SourceMap.VERSION
    # No filesystem paths leak into the map, so it works from any directory to load.
    assert str(tmp_path) not in text

    monkeypatch.chdir(tmp_path)
    loaded = SourceMap.load(map_file)
    assert loaded == source_map
    assert 'clé' in loaded.to_json()
    with open(map_file, encoding='utf-8') as f:
        assert SourceMap.load(f) == source_map


def test_source_map_disabled_by_default():
    validate = fastjsonschema.compile({'type': 'string'})
    assert callable(validate)
    validate('ok')

    code = fastjsonschema.compile_to_code({'type': 'string'})
    assert isinstance(code, str)
    assert 'def validate(' in code


def test_source_map_with_fast_fail_off():
    validate, source_map = fastjsonschema.compile(
        SCHEMA, handlers=HANDLERS, source_map=True, fast_fail=False,
    )
    with pytest.raises(fastjsonschema.JsonSchemaValuesException):
        validate({'thing': make_valid_thing(**{'clé': 3})})
    assert source_map.entries
