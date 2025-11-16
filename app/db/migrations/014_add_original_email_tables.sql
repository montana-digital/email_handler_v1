-- Adds tables storing original emails and attachments for reliable exports.

CREATE TABLE IF NOT EXISTS original_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_hash TEXT UNIQUE NOT NULL,
    file_name TEXT,
    mime_type TEXT,
    content BLOB NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS original_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_hash TEXT NOT NULL,
    file_name TEXT,
    mime_type TEXT,
    content BLOB NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (email_hash) REFERENCES original_emails(email_hash) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_original_attachments_hash ON original_attachments(email_hash);

