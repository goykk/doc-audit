-- v4: composite index for status + field-path prefix search.
ALTER TABLE review_items
    ADD KEY idx_review_status_field (status, field_path(64), id);
