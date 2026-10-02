from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO
from urllib.parse import quote, unquote, urldefrag, urljoin


LOCATION_MAP_ATTRIBUTE = "__fastjsonschema_location_map__"


def escape_json_pointer(token: str | int) -> str:
    return "/" + str(token).replace("~", "~0").replace("/", "~1")


@dataclass(frozen=True)
class SchemaPosition:
    resource: str
    pointer: str = ""

    @classmethod
    def from_uri(cls, uri: str) -> "SchemaPosition":
        resource, fragment = urldefrag(uri)
        if not fragment:
            return cls(resource)
        if fragment.startswith("/"):
            pointer = "/".join(
                unquote(part.replace("~1", "/").replace("~0", "~"))
                for part in fragment.split("/")[1:]
            )
            return cls(resource, "/" + pointer if pointer else "")
        return cls(resource, "#" + fragment)

    def child(self, token: str | int, definition: Any | None = None) -> "SchemaPosition":
        if isinstance(definition, dict):
            schema_id = definition.get("$id", definition.get("id"))
            if isinstance(schema_id, str):
                return SchemaPosition.from_uri(urljoin(self.resource or "", schema_id))
        return type(self)(self.resource, self.pointer + escape_json_pointer(token))

    @property
    def uri(self) -> str:
        if not self.pointer:
            return self.resource
        if self.pointer.startswith("#"):
            return self.resource + self.pointer
        return self.resource + "#" + quote(self.pointer, safe="/~")

    def to_dict(self) -> dict[str, str]:
        return {
            "resource_uri": self.resource,
            "json_pointer": self.pointer,
            "schema_uri": self.uri,
        }


@dataclass
class FunctionLocation:
    name: str
    position: SchemaPosition
    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            **self.position.to_dict(),
        }


@dataclass
class RuleLocation:
    function: str
    position: SchemaPosition
    rule: str | None
    start_line: int
    end_line: int
    id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "function": self.function,
            "rule": self.rule,
            "start_line": self.start_line,
            "end_line": self.end_line,
            **self.position.to_dict(),
        }
        if self.id is not None:
            data["id"] = self.id
        return data


@dataclass
class ReferenceLocation:
    function: str
    source: SchemaPosition
    target: SchemaPosition
    reference: str
    start_line: int
    end_line: int
    id: int | None = None

    @property
    def rule(self) -> str:
        return "$ref"

    def to_dict(self) -> dict[str, Any]:
        data = {
            "function": self.function,
            "rule": "$ref",
            "reference": self.reference,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
        }
        if self.id is not None:
            data["id"] = self.id
        return data


@dataclass(frozen=True)
class ExceptionLocation:
    rule: RuleLocation | None
    references: tuple[ReferenceLocation, ...]

    @property
    def definition(self) -> SchemaPosition | None:
        if self.rule is None:
            return None
        return self.rule.position

    @property
    def reference_path(self) -> tuple[SchemaPosition, ...]:
        return tuple(reference.source for reference in self.references)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": None if self.rule is None else self.rule.to_dict(),
            "references": [reference.to_dict() for reference in self.references],
            "reference_path": [position.to_dict() for position in self.reference_path],
        }


def _position_from_dict(data: dict[str, Any]) -> SchemaPosition:
    return SchemaPosition(
        resource=data.get("resource_uri", ""),
        pointer=data.get("json_pointer", ""),
    )


class LocationMap:
    """
    JSON-serializable map from generated Python line ranges to schema nodes.
    """

    def __init__(self) -> None:
        self.version = 1
        self.map_id = uuid.uuid4().hex
        self.code_sha256: str | None = None
        self.entry_function: str | None = None
        self._next_id = 1
        self.functions: dict[str, FunctionLocation] = {}
        self.rules: list[RuleLocation] = []
        self.references: list[ReferenceLocation] = []

    def new_id(self) -> int:
        location_id = self._next_id
        self._next_id += 1
        return location_id

    def set_code(self, code: str) -> None:
        self.code_sha256 = hashlib.sha256(code.encode("utf-8")).hexdigest()

    def record_function(
        self,
        name: str,
        position: SchemaPosition,
        start_line: int,
        end_line: int,
    ) -> None:
        self.functions[name] = FunctionLocation(name, position, start_line, end_line)
        if self.entry_function is None:
            self.entry_function = name

    def record_rule(
        self,
        name: str,
        position: SchemaPosition,
        rule: str | None,
        start_line: int,
        end_line: int,
        location_id: int | None = None,
    ) -> None:
        if start_line > end_line:
            return
        self.rules.append(
            RuleLocation(name, position, rule, start_line, end_line, location_id)
        )

    def record_reference(
        self,
        name: str,
        source: SchemaPosition,
        target: SchemaPosition,
        reference: str,
        start_line: int,
        end_line: int,
        location_id: int | None = None,
    ) -> None:
        self.references.append(
            ReferenceLocation(
                name, source, target, reference, start_line, end_line, location_id
            )
        )

    def find_rule_by_id(self, location_id: int) -> RuleLocation | None:
        for rule in self.rules:
            if rule.id == location_id:
                return rule
        return None

    def find_reference_by_id(self, location_id: int) -> ReferenceLocation | None:
        for reference in self.references:
            if reference.id == location_id:
                return reference
        return None

    def shift_lines(self, offset: int) -> None:
        for function in self.functions.values():
            function.start_line += offset
            function.end_line += offset
        for rule in self.rules:
            rule.start_line += offset
            rule.end_line += offset
        for reference in self.references:
            reference.start_line += offset
            reference.end_line += offset

    @staticmethod
    def _contains(start: int, end: int, line: int) -> bool:
        return start <= line <= end

    def find_rule(self, function: str, line: int) -> RuleLocation | None:
        candidates = [
            rule
            for rule in self.rules
            if rule.function == function and self._contains(rule.start_line, rule.end_line, line)
        ]
        if not candidates:
            return None
        exact_line = [
            rule
            for rule in candidates
            if rule.id is not None and rule.start_line == line == rule.end_line
        ]
        if exact_line:
            return exact_line[-1]
        return min(candidates, key=lambda rule: (rule.end_line - rule.start_line, -rule.start_line))

    def find_reference(self, function: str, line: int) -> ReferenceLocation | None:
        for reference in self.references:
            if (
                reference.function == function
                and self._contains(reference.start_line, reference.end_line, line)
            ):
                return reference
        return None

    def _frame_belongs_to_map(self, frame: Any) -> bool:
        function = frame.f_globals.get(frame.f_code.co_name)
        attached_map = getattr(function, LOCATION_MAP_ATTRIBUTE, None)
        if attached_map is not None:
            return attached_map is self
        if frame.f_globals.get("LOCATION_MAP_ID") != self.map_id:
            return False
        function_location = self.functions.get(frame.f_code.co_name)
        return (
            function_location is not None
            and function_location.start_line <= frame.f_lineno <= function_location.end_line
        )

    def _generated_frames(self, traceback: TracebackType) -> list[tuple[str, int]]:
        frames = []
        while traceback is not None:
            frame = traceback.tb_frame
            name = frame.f_code.co_name
            if name in self.functions and self._frame_belongs_to_map(frame):
                frames.append((name, traceback.tb_lineno))
            traceback = traceback.tb_next
        return frames

    def locate(self, exception_or_traceback: BaseException | TracebackType) -> ExceptionLocation:
        is_exception = hasattr(exception_or_traceback, "__traceback__")
        if is_exception:
            if hasattr(exception_or_traceback, "rule_id"):
                rule_id = exception_or_traceback.rule_id
                ref_ids = getattr(exception_or_traceback, "ref_path", ())
                if rule_id is None or isinstance(rule_id, int):
                    rule = self.find_rule_by_id(rule_id)
                    references = tuple(
                        reference
                        for reference_id in ref_ids
                        if isinstance(reference_id, int)
                        for reference in [self.find_reference_by_id(reference_id)]
                        if reference is not None
                    )
                    return ExceptionLocation(rule, references)

        if is_exception:
            traceback = exception_or_traceback.__traceback__
            frames = self._generated_frames(traceback)
            errors = getattr(exception_or_traceback, "errors", None)
            for error in errors or ():
                location = self.locate(error)
                if location.rule is not None or location.references:
                    return location
        else:
            traceback = exception_or_traceback
            frames = self._generated_frames(traceback)

        references = []
        for name, line in frames:
            reference = self.find_reference(name, line)
            if reference is not None:
                references.append(reference)

        rule = None
        if frames:
            name, line = frames[-1]
            rule = self.find_rule(name, line)

        return ExceptionLocation(rule, tuple(references))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "map_id": self.map_id,
            "code_sha256": self.code_sha256,
            "entry_function": self.entry_function,
            "functions": {
                name: function.to_dict()
                for name, function in self.functions.items()
            },
            "rules": [rule.to_dict() for rule in self.rules],
            "references": [reference.to_dict() for reference in self.references],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LocationMap":
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported fastjsonschema location map version")
        location_map = cls()
        map_id = data.get("map_id")
        location_map.map_id = map_id if isinstance(map_id, str) else uuid.uuid4().hex
        location_map.code_sha256 = data.get("code_sha256")
        entry_function = data.get("entry_function")
        location_map.entry_function = entry_function if isinstance(entry_function, str) else None
        for name, item in data.get("functions", {}).items():
            if not isinstance(name, str) or not isinstance(item, dict):
                raise ValueError("Invalid fastjsonschema location map functions")
            location_map.functions[name] = FunctionLocation(
                name,
                _position_from_dict(item),
                int(item["start_line"]),
                int(item["end_line"]),
            )
        for item in data.get("rules", []):
            if not isinstance(item, dict):
                raise ValueError("Invalid fastjsonschema location map rules")
            location_map.rules.append(
                RuleLocation(
                    item["function"],
                    _position_from_dict(item),
                    item.get("rule"),
                    int(item["start_line"]),
                    int(item["end_line"]),
                    id=item.get("id") if isinstance(item.get("id"), int) else None,
                )
            )
        for item in data.get("references", []):
            if not isinstance(item, dict) or not isinstance(item.get("source"), dict):
                raise ValueError("Invalid fastjsonschema location map references")
            location_map.references.append(
                ReferenceLocation(
                    item["function"],
                    _position_from_dict(item["source"]),
                    _position_from_dict(item["target"]),
                    item["reference"],
                    int(item["start_line"]),
                    int(item["end_line"]),
                    id=item.get("id") if isinstance(item.get("id"), int) else None,
                )
            )
        if location_map.rules or location_map.references:
            location_map._next_id = 1 + max(
                item.id or 0
                for item in location_map.rules + location_map.references
            )
        return location_map

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, data: str | bytes) -> "LocationMap":
        return cls.from_dict(json.loads(data))

    def dump(self, file: str | Path | TextIO, *, indent: int = 2) -> None:
        if hasattr(file, "write"):
            json.dump(self.to_dict(), file, ensure_ascii=False, indent=indent)
        else:
            with open(file, "w", encoding="utf-8") as opened_file:
                json.dump(self.to_dict(), opened_file, ensure_ascii=False, indent=indent)

    @classmethod
    def load(cls, file: str | Path | TextIO) -> "LocationMap":
        if hasattr(file, "read"):
            return cls.from_dict(json.load(file))
        with open(file, encoding="utf-8") as opened_file:
            return cls.from_dict(json.load(opened_file))


def get_exception_location(
    exception: BaseException,
    location_map: LocationMap | None = None,
) -> ExceptionLocation | None:
    if location_map is None:
        traceback = exception.__traceback__
        while traceback is not None:
            function = traceback.tb_frame.f_globals.get(traceback.tb_frame.f_code.co_name)
            attached_map = getattr(function, LOCATION_MAP_ATTRIBUTE, None)
            if isinstance(attached_map, LocationMap):
                location_map = attached_map
                break
            traceback = traceback.tb_next
    if location_map is None:
        return None
    return location_map.locate(exception)


SourceMap = LocationMap
