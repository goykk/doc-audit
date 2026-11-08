-- DocAudit schema v1. All tables utf8mb4; monetary values are kept as strings/JSON
-- inside extraction payloads and converted to Decimal inside the validation layer.

CREATE TABLE IF NOT EXISTS documents (
    id              BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    doc_id          VARCHAR(64)  NOT NULL UNIQUE COMMENT 'business id, e.g. cord_0001',
    filename        VARCHAR(255) NOT NULL,
    doc_type        VARCHAR(32)  NOT NULL DEFAULT 'receipt' COMMENT 'cn_invoice/receipt/layout',
    source_dataset  VARCHAR(32)  NOT NULL DEFAULT 'synthetic' COMMENT 'cord/sroie/funsd/synthetic',
    quality_tier    VARCHAR(16)  NOT NULL DEFAULT 'clear' COMMENT 'clear/scan/lowres',
    layout_tier     VARCHAR(32)  NOT NULL DEFAULT 'single_column',
    page_count      INT          NOT NULL DEFAULT 1,
    status          VARCHAR(16)  NOT NULL DEFAULT 'uploaded' COMMENT 'uploaded/extracted/accepted/review/rejected',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_documents_dataset (source_dataset, quality_tier, layout_tier)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS extractions (
    id                 BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    document_id        BIGINT UNSIGNED NOT NULL,
    pipeline           VARCHAR(16)  NOT NULL COMMENT 'layout_llm/vlm_e2e',
    model              VARCHAR(64)  NOT NULL DEFAULT '',
    result_json        JSON         NOT NULL COMMENT 'full ExtractionResult',
    latency_ms         INT          NOT NULL DEFAULT 0,
    prompt_tokens      INT          NOT NULL DEFAULT 0,
    completion_tokens  INT          NOT NULL DEFAULT 0,
    cost_cny           DECIMAL(10,6) NOT NULL DEFAULT 0,
    error              TEXT         NULL,
    created_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_extractions_document FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    KEY idx_extractions_doc (document_id, pipeline)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS field_values (
    id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    extraction_id  BIGINT UNSIGNED NOT NULL,
    field_path     VARCHAR(128) NOT NULL COMMENT 'e.g. amount_total or line_items[0].amount',
    field_value    JSON         NULL COMMENT 'NULL means genuinely absent, never an extraction error',
    quote          TEXT         NULL,
    bbox           JSON         NULL COMMENT '{x0,y0,x1,y1,page}, pixels at render dpi',
    confidence     DECIMAL(4,3) NOT NULL DEFAULT 1.000,
    source         VARCHAR(16)  NOT NULL DEFAULT 'llm' COMMENT 'llm/vlm/parser/reviewer',
    CONSTRAINT fk_field_values_extraction FOREIGN KEY (extraction_id) REFERENCES extractions (id) ON DELETE CASCADE,
    KEY idx_field_values_path (extraction_id, field_path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS validations (
    id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    extraction_id  BIGINT UNSIGNED NOT NULL,
    rule_hits      JSON         NOT NULL COMMENT '[{rule_id,level,field_path,message}]',
    passed         TINYINT(1)   NOT NULL DEFAULT 0,
    warn_count     INT          NOT NULL DEFAULT 0,
    error_count    INT          NOT NULL DEFAULT 0,
    status         VARCHAR(16)  NOT NULL DEFAULT 'review' COMMENT 'accepted/review/rejected',
    audit_log      JSON         NULL COMMENT 're-extraction attempts and reviewer actions',
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_validations_extraction FOREIGN KEY (extraction_id) REFERENCES extractions (id) ON DELETE CASCADE,
    KEY idx_validations_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS review_items (
    id              BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
    document_id     BIGINT UNSIGNED NOT NULL,
    extraction_id   BIGINT UNSIGNED NOT NULL,
    field_path      VARCHAR(128) NULL COMMENT 'NULL for document-level issues such as duplicates',
    rule_id         VARCHAR(64)  NOT NULL,
    reason          TEXT         NOT NULL,
    original_value  JSON         NULL,
    suggested_value JSON         NULL COMMENT 'validator proposal, e.g. recomputed amount_total',
    status          VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending/accepted/corrected/rejected',
    reviewer_note   TEXT         NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at     DATETIME     NULL,
    CONSTRAINT fk_review_document FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT fk_review_extraction FOREIGN KEY (extraction_id) REFERENCES extractions (id) ON DELETE CASCADE,
    KEY idx_review_status (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
