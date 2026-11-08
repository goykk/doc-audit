-- v5: document list filtering indexes.
ALTER TABLE documents
    ADD KEY idx_documents_dataset_status (source_dataset, status, id),
    ADD KEY idx_documents_dataset_id (source_dataset, id);
