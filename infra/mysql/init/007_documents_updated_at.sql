-- v7: document update timestamp for recency ordering.
ALTER TABLE documents
    ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

UPDATE documents SET updated_at = created_at;
