import importlib.util
import json
from copy import deepcopy

import pytest

from fastjsonschema import (
    JsonSchemaValuesException,
    compile,
    compile_to_code,
    get_exception_location,
)
from fastjsonschema.source_map import SchemaPosition


LOCAL_RESOURCE = "https://schemas.example.test/local/main.json"
REMOTE_RESOURCE = "https://schemas.example.test/remote/schema.json"
SHARED_RESOURCE = "https://schemas.example.test/remote/shared.json"
NESTED_RESOURCE = "https://schemas.example.test/remote/nested"


def build_schemas():
    return {
        REMOTE_RESOURCE: {
            "$id": REMOTE_RESOURCE,
            "$defs": {
                "node/base": {
                    "$id": "nested",
                    "type": "object",
                    "properties": {
                        "a/~字": {"$ref": "shared.json#/$defs/shared/properties/type"},
                    },
                },
            },
        },
        SHARED_RESOURCE: {
            "$id": SHARED_RESOURCE,
            "$defs": {
                "shared": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "minLength": 5},
                    },
                },
            },
        },
    }


def build_schema():
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": LOCAL_RESOURCE,
        "type": "object",
        "properties": {
            "x/y~字": {"$ref": REMOTE_RESOURCE + "#/$defs/node~1base"},
            "other/y": {"$ref": SHARED_RESOURCE + "#/$defs/shared/properties/type"},
        },
    }


def invalid_nested_data():
    return {"x/y~字": {"a/~字": 1}}


def assert_nested_location(location):
    assert location is not None
    assert location.rule.position.resource == SHARED_RESOURCE
    assert location.rule.position.pointer == "/$defs/shared/properties/type"
    assert location.rule.rule == "type"
    assert [(item.resource, item.pointer) for item in location.reference_path] == [
        (LOCAL_RESOURCE, "/properties/x~1y~0字"),
        (NESTED_RESOURCE, "/properties/a~1~0字"),
    ]


def test_memory_compile_locates_cross_resource_rule():
    schemas = deepcopy(build_schemas())
    validator = compile(
        build_schema(),
        handlers={"https": lambda uri: schemas[uri]},
        location_map=True,
    )

    with pytest.raises(Exception) as exc_info:
        validator(invalid_nested_data())

    assert_nested_location(get_exception_location(exc_info.value))


def test_compile_to_code_locates_same_node_with_saved_json_map(tmp_path):
    schemas = deepcopy(build_schemas())
    code, location_map = compile_to_code(
        build_schema(),
        handlers={"https": lambda uri: schemas[uri]},
        location_map=True,
    )

    module_path = tmp_path / "generated_validator.py"
    map_path = tmp_path / "generated_validator.location.json"
    module_path.write_text(code, encoding="utf-8")
    location_map.dump(map_path)

    saved_data = json.loads(map_path.read_text(encoding="utf-8"))
    assert saved_data["version"] == 1
    assert saved_data["entry_function"] == location_map.entry_function
    assert saved_data["rules"]
    assert saved_data["references"]

    spec = importlib.util.spec_from_file_location("generated_validator", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loaded_map = type(location_map).load(map_path)
    assert module.LOCATION_MAP_ID == loaded_map.map_id
    validator = getattr(module, loaded_map.entry_function)

    with pytest.raises(Exception) as exc_info:
        validator(invalid_nested_data())

    assert_nested_location(loaded_map.locate(exc_info.value))


def test_same_generated_function_keeps_current_reference_entry():
    schemas = deepcopy(build_schemas())
    validator = compile(
        build_schema(),
        handlers={"https": lambda uri: schemas[uri]},
        location_map=True,
    )

    with pytest.raises(Exception) as first:
        validator(invalid_nested_data())
    with pytest.raises(Exception) as second:
        validator({"other/y": "bad"})

    first_location = get_exception_location(first.value)
    second_location = get_exception_location(second.value)
    assert first_location.reference_path[-1].pointer == "/properties/a~1~0字"
    assert second_location.reference_path[0].pointer == "/properties/other~1y"


def test_composition_branches_have_positions_and_reference_path():
    schema = {
        "allOf": [{"$ref": "#/$defs/a"}],
        "$defs": {"a": {"type": "string"}},
    }
    validator = compile(schema, location_map=True)

    with pytest.raises(Exception) as exc_info:
        validator(1)

    location = get_exception_location(exc_info.value)
    assert location.rule.position.pointer == "/$defs/a"
    assert location.reference_path[0].pointer == "/allOf/0"

    _, location_map = compile_to_code(
        {
            "anyOf": [
                {"type": "string"},
                {"type": "number"},
            ]
        },
        location_map=True,
    )
    pointers = {rule.position.pointer for rule in location_map.rules}
    assert "/anyOf/0" in pointers
    assert "/anyOf/1" in pointers


def test_location_map_supports_collected_errors():
    schemas = deepcopy(build_schemas())
    validator = compile(
        build_schema(),
        handlers={"https": lambda uri: schemas[uri]},
        fast_fail=False,
        location_map=True,
    )

    with pytest.raises(JsonSchemaValuesException) as exc_info:
        validator(invalid_nested_data())

    assert_nested_location(get_exception_location(exc_info.value))


def test_location_map_round_trip_is_plain_json_with_unicode():
    schemas = deepcopy(build_schemas())
    _, location_map = compile_to_code(
        build_schema(),
        handlers={"https": lambda uri: schemas[uri]},
        location_map=True,
    )

    raw = location_map.to_json()
    assert "a~1~0字" in raw
    loaded = type(location_map).from_json(raw)
    assert loaded.code_sha256 == location_map.code_sha256
    with pytest.raises(ValueError):
        type(location_map).from_json(json.dumps({"version": 2}))


@pytest.mark.parametrize("fast_fail", [True, False])
def test_location_map_works_without_detailed_exceptions(fast_fail):
    validator = compile(
        {"type": "string"},
        detailed_exceptions=False,
        fast_fail=fast_fail,
        location_map=True,
    )

    with pytest.raises(Exception) as exc_info:
        validator(1)

    location = get_exception_location(exc_info.value)
    assert location.rule.position.pointer == ""
    assert location.rule.rule == "type"


@pytest.mark.parametrize(
    ("uri", "resource", "pointer"),
    [
        ("https://x/a#/p%2Fq", "https://x/a", "/p/q"),
        ("https://x/a#/p~1q", "https://x/a", "/p/q"),
        ("https://x/a#/p%7E1q", "https://x/a", "/p~1q"),
        ("https://x/a#/%E5%AD%97", "https://x/a", "/字"),
    ],
)
def test_schema_position_decodes_uri_fragment(uri, resource, pointer):
    position = SchemaPosition.from_uri(uri)
    assert position.resource == resource
    assert position.pointer == pointer
