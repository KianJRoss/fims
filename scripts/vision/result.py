from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TextRegion:
    text: str
    bbox: list[float]
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": list(self.bbox),
            "confidence": self.confidence,
        }


@dataclass(slots=True)
class Code:
    kind: str
    data: str
    bbox: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "data": self.data,
            "bbox": None if self.bbox is None else list(self.bbox),
        }


@dataclass(slots=True)
class Subject:
    bbox: list[float]
    crop_path: str | None = None
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bbox": list(self.bbox),
            "crop_path": self.crop_path,
            "label": self.label,
        }


@dataclass(slots=True)
class Analysis:
    source: str
    width: int
    height: int
    texts: list[TextRegion] = field(default_factory=list)
    codes: list[Code] = field(default_factory=list)
    subjects: list[Subject] = field(default_factory=list)
    vlm: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "texts": [item.to_dict() for item in self.texts],
            "codes": [item.to_dict() for item in self.codes],
            "subjects": [item.to_dict() for item in self.subjects],
            "vlm": self.vlm,
            "meta": self.meta,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

