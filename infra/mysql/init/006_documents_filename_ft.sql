-- v6: ngram fulltext for filename search.
ALTER TABLE documents
    ADD FULLTEXT KEY ft_documents_filename (filename) WITH PARSER ngram;
