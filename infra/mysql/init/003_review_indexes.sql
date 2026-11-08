-- v3: review queue filtering/search indexes.
ALTER TABLE review_items
    ADD KEY idx_review_status_rule_id (status, rule_id, id),
    ADD KEY idx_review_status_id (status, id),
    ADD KEY idx_review_field_path (field_path(64)),
    ADD FULLTEXT KEY ft_review_reason (reason) WITH PARSER ngram;
