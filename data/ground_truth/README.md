# Ground truth 存放说明

- 标注文件：`{doc_id}.json`，内容为一个 `ExtractionResult`（`pipeline` 字段在标注时填 `layout_llm`，评测时忽略）。
- 每个样本的元信息（`quality_tier`、`layout_tier`、`source_dataset`、`doc_type`）写入同目录 `manifest.jsonl`。
- `dataset_fields.yaml` 是评分白名单，**不属于白名单的字段不参与 F1**。
- 标注前必读 `docs/annotation_spec.md`。
- 本目录不提交任何真实票据数据；公开数据集由脚本下载，合成数据由生成脚本产出。
