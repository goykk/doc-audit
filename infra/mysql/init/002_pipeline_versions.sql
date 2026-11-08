-- v2: keep route A and route B extractions side by side.
ALTER TABLE extractions
    ADD COLUMN is_current TINYINT(1) NOT NULL DEFAULT 1 AFTER pipeline,
    ADD UNIQUE KEY uq_extraction_document_pipeline (document_id, pipeline),
    ADD KEY idx_extractions_current (document_id, is_current);

-- Existing databases have exactly one extraction per document; it becomes current.
