-- v8: recent-document ordering index.
ALTER TABLE documents
    ADD KEY idx_documents_updated (updated_at, id);
