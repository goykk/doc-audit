-- v9: resolved review audit indexes.
ALTER TABLE review_items
    ADD KEY idx_review_resolved (resolved_at),
    ADD KEY idx_review_status_resolved (status, resolved_at);
