"""Load manifests/ground truth/predictions and evaluate a dataset."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from app.evaluation.metrics import FieldSpec, Sample, evaluate
from app.extraction_result import ExtractionResult


def load_field_specs(path: Path) -> dict[str, FieldSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    specs: dict[str, FieldSpec] = {}
    for dataset, config in raw.items():
        specs[dataset] = FieldSpec(
            fields=list(config.get("fields") or []),
            line_items=list(config.get("line_items") or []),
        )
    return specs


def load_manifest(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on {path}:{line_no}: {exc}") from exc
    return rows


def _load_result(path: Path) -> ExtractionResult:
    if not path.is_file():
        raise FileNotFoundError(path)
    return ExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))


def build_samples(
    manifest_path: Path,
    pred_dir: Path,
    project_root: Path,
    dataset: str,
) -> list[Sample]:
    rows = load_manifest(manifest_path)
    samples: list[Sample] = []
    missing: list[str] = []
    for row in rows:
        if dataset and row.get("source_dataset") != dataset:
            continue
        doc_id = row["doc_id"]
        gt_path = project_root / row["annotation"]
        pred_path = pred_dir / f"{doc_id}.json"
        if not pred_path.is_file():
            missing.append(doc_id)
            continue
        truth = _load_result(gt_path)
        pred = _load_result(pred_path)
        if truth.doc_id != doc_id or pred.doc_id != doc_id:
            raise ValueError(f"doc_id mismatch for {doc_id}")
        samples.append(
            Sample(
                doc_id=doc_id,
                dataset=row.get("source_dataset", "unknown"),
                truth=truth,
                pred=pred,
                quality_tier=row.get("quality_tier", "unknown"),
                layout_tier=row.get("layout_tier", "unknown"),
            )
        )
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} predictions missing in {pred_dir}: {', '.join(missing[:10])}"
        )
    if not samples:
        raise ValueError(f"no samples matched dataset={dataset!r}")
    return samples


def run_evaluation(
    manifest_path: Path,
    pred_dir: Path,
    fields_path: Path,
    project_root: Path,
    dataset: str | None = None,
) -> dict:
    specs = load_field_specs(fields_path)
    if dataset is None:
        datasets = {row.get("source_dataset") for row in load_manifest(manifest_path)}
        if len(datasets) != 1:
            raise ValueError(f"manifest spans multiple datasets {sorted(datasets)}; pass dataset explicitly")
        dataset = datasets.pop()
    spec = specs.get(dataset)
    if spec is None:
        raise KeyError(f"no field whitelist for dataset {dataset!r}")
    samples = build_samples(manifest_path, pred_dir, project_root, dataset=dataset)
    return evaluate(samples, spec)
