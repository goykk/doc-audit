"""Single extraction contract shared by both pipelines.

Route A (MinerU + LLM) and route B (VLM end-to-end) MUST both return this model,
otherwise field-level metrics are not comparable.

Null semantics (part of the annotation spec):
- value=None  -> the field is genuinely absent / not applicable on the document.
- a wrong non-null value -> an extraction error.
These two cases are scored differently and must never be conflated.
"""
from __future__ import annotations

from typing import Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
    """Pixel coordinates on a page rendered at `dpi` (default 200)."""

    model_config = ConfigDict(extra="forbid")

    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)
    page: int = Field(ge=1)

    def iou(self, other: "BoundingBox") -> float:
        if self.page != other.page:
            return 0.0
        ix0, iy0 = max(self.x0, other.x0), max(self.y0, other.y0)
        ix1, iy1 = min(self.x1, other.x1), min(self.y1, other.y1)
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        if inter == 0:
            return 0.0
        a = (self.x1 - self.x0) * (self.y1 - self.y0)
        b = (other.x1 - other.x0) * (other.y1 - other.y0)
        return inter / (a + b - inter) if a + b - inter > 0 else 0.0


class FieldValue(BaseModel):
    """One extracted scalar, plus its evidence."""

    model_config = ConfigDict(extra="forbid")

    value: Any = None
    quote: str | None = Field(
        default=None,
        description="Verbatim substring copied from the source text; used to locate the bbox.",
    )
    bbox: BoundingBox | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Literal["llm", "vlm", "parser", "reviewer"] = "llm"


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: FieldValue = Field(default_factory=FieldValue)
    quantity: FieldValue = Field(default_factory=FieldValue)
    unit_price: FieldValue = Field(default_factory=FieldValue)
    amount: FieldValue = Field(default_factory=FieldValue)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    doc_type: Literal["cn_invoice", "receipt", "layout"] = "receipt"
    pipeline: Literal["layout_llm", "vlm_e2e", "merged"]
    model: str = ""
    fields: dict[str, FieldValue] = Field(default_factory=dict)
    line_items: list[LineItem] = Field(default_factory=list)
    latency_ms: int = 0
    parse_latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_cny: float = 0.0

    def iter_fields(self) -> Iterator[tuple[str, FieldValue]]:
        """Flatten to `field_path` -> FieldValue, e.g. `line_items[0].amount`."""
        for name, fv in self.fields.items():
            yield name, fv
        for idx, item in enumerate(self.line_items):
            for name in ("description", "quantity", "unit_price", "amount"):
                yield f"line_items[{idx}].{name}", getattr(item, name)

    def flat_values(self) -> dict[str, Any]:
        return {path: fv.value for path, fv in self.iter_fields()}

    def min_confidence(self) -> float:
        confs = [fv.confidence for _, fv in self.iter_fields() if fv.value is not None]
        return min(confs) if confs else 0.0
