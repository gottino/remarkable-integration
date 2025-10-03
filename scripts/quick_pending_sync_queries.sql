-- Quick SQL Queries to Find Pending Sync Items
-- Use these with: sqlite3 data/remarkable_pipeline.db

-- ===========================================
-- 1. NOTEBOOKS NEEDING SYNC TO NOTION
-- ===========================================

-- Notebooks never synced to Notion
SELECT
    'NEVER SYNCED' as status,
    nm.notebook_uuid,
    nm.visible_name,
    nm.full_path,
    COUNT(nte.id) as page_count,
    MAX(nte.updated_at) as last_content_update,
    datetime(CAST(nm.last_opened AS INTEGER) / 1000, 'unixepoch') as last_opened_readable
FROM notebook_metadata nm
LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
    AND nte.text IS NOT NULL AND LENGTH(nte.text) > 0
LEFT JOIN sync_records sr ON (
    sr.item_id = nm.notebook_uuid
    AND sr.target_name = 'notion'
    AND sr.item_type = 'notebook'
    AND sr.status = 'success'
)
WHERE nm.deleted = FALSE
    AND sr.id IS NULL
    AND nte.id IS NOT NULL  -- Has content
GROUP BY nm.notebook_uuid, nm.visible_name, nm.full_path, nm.last_opened
ORDER BY last_content_update DESC;

-- ===========================================
-- 2. FAILED SYNC RECORDS
-- ===========================================

-- All failed sync attempts
SELECT
    target_name,
    item_type,
    item_id,
    status,
    error_message,
    retry_count,
    updated_at,
    created_at
FROM sync_records
WHERE status != 'success'
ORDER BY updated_at DESC;

-- ===========================================
-- 3. NOTEBOOKS WITH MOST RECENT ACTIVITY
-- ===========================================

-- Show notebooks ordered by recent activity (last opened)
SELECT
    nm.visible_name,
    nm.notebook_uuid,
    datetime(CAST(nm.last_opened AS INTEGER) / 1000, 'unixepoch') as last_opened_readable,
    COUNT(nte.id) as page_count,
    SUM(LENGTH(nte.text)) as total_characters,
    MAX(nte.updated_at) as last_content_update,
    sr.synced_at as last_notion_sync,
    CASE
        WHEN sr.id IS NULL THEN 'NEVER SYNCED'
        WHEN sr.status = 'success' THEN 'SYNCED'
        ELSE sr.status
    END as notion_sync_status
FROM notebook_metadata nm
LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
    AND nte.text IS NOT NULL AND LENGTH(nte.text) > 0
LEFT JOIN sync_records sr ON (
    sr.item_id = nm.notebook_uuid
    AND sr.target_name = 'notion'
    AND sr.item_type = 'notebook'
    AND sr.status = 'success'
)
WHERE nm.deleted = FALSE
    AND nte.id IS NOT NULL  -- Has content
GROUP BY nm.notebook_uuid, nm.visible_name, nm.last_opened, sr.synced_at, sr.status
ORDER BY CAST(nm.last_opened AS INTEGER) DESC
LIMIT 20;

-- ===========================================
-- 4. TODOS NEEDING SYNC
-- ===========================================

-- Todos never synced to any target
SELECT
    'TODO' as type,
    t.id,
    t.text,
    t.notebook_uuid,
    nm.visible_name as notebook_name,
    t.page_number,
    t.updated_at,
    CASE
        WHEN sr_notion.id IS NULL THEN 'NOT_SYNCED_NOTION'
        ELSE 'SYNCED_NOTION'
    END as notion_status,
    CASE
        WHEN sr_todo.id IS NULL THEN 'NOT_SYNCED_TODO_TARGET'
        ELSE 'SYNCED_TODO_TARGET'
    END as todo_target_status
FROM todos t
LEFT JOIN notebook_metadata nm ON t.notebook_uuid = nm.notebook_uuid
LEFT JOIN sync_records sr_notion ON (
    sr_notion.item_id = CAST(t.id AS TEXT)
    AND sr_notion.target_name = 'notion'
    AND sr_notion.item_type = 'todo'
    AND sr_notion.status = 'success'
)
LEFT JOIN sync_records sr_todo ON (
    sr_todo.item_id = CAST(t.id AS TEXT)
    AND sr_todo.target_name = 'notion_todos'
    AND sr_todo.item_type = 'todo'
    AND sr_todo.status = 'success'
)
WHERE t.completed = FALSE
    AND (sr_notion.id IS NULL OR sr_todo.id IS NULL)
ORDER BY t.updated_at DESC;

-- ===========================================
-- 5. HIGHLIGHTS NEEDING SYNC TO READWISE
-- ===========================================

-- Highlights never synced to Readwise
SELECT
    'HIGHLIGHT' as type,
    eh.id,
    eh.title,
    SUBSTR(COALESCE(eh.corrected_text, eh.original_text), 1, 100) as text_preview,
    eh.source_file,
    eh.page_number,
    eh.confidence,
    eh.updated_at,
    CASE
        WHEN sr.id IS NULL THEN 'NEVER_SYNCED'
        ELSE sr.status
    END as readwise_sync_status
FROM enhanced_highlights eh
LEFT JOIN sync_records sr ON (
    sr.item_id = CAST(eh.id AS TEXT)
    AND sr.target_name = 'readwise'
    AND sr.item_type = 'highlight'
    AND sr.status = 'success'
)
WHERE sr.id IS NULL
ORDER BY eh.updated_at DESC
LIMIT 20;

-- ===========================================
-- 6. SYNC SUMMARY STATISTICS
-- ===========================================

-- Overall sync statistics by target and type
SELECT
    'SYNC_SUMMARY' as report,
    target_name,
    item_type,
    status,
    COUNT(*) as count,
    MIN(created_at) as first_sync,
    MAX(synced_at) as latest_sync
FROM sync_records
GROUP BY target_name, item_type, status
ORDER BY target_name, item_type, status;

-- ===========================================
-- 7. CONTENT ANALYSIS - LARGEST NOTEBOOKS
-- ===========================================

-- Notebooks with most content (might be good candidates for testing)
SELECT
    nm.visible_name,
    nm.notebook_uuid,
    COUNT(nte.id) as page_count,
    SUM(LENGTH(nte.text)) as total_characters,
    AVG(nte.confidence) as avg_confidence,
    MAX(nte.updated_at) as last_content_update,
    datetime(CAST(nm.last_opened AS INTEGER) / 1000, 'unixepoch') as last_opened_readable,
    CASE
        WHEN sr.id IS NULL THEN 'NEEDS_SYNC'
        WHEN sr.status = 'success' THEN 'SYNCED'
        ELSE sr.status
    END as notion_sync_status
FROM notebook_metadata nm
LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
    AND nte.text IS NOT NULL AND LENGTH(nte.text) > 0
LEFT JOIN sync_records sr ON (
    sr.item_id = nm.notebook_uuid
    AND sr.target_name = 'notion'
    AND sr.item_type = 'notebook'
    AND sr.status = 'success'
)
WHERE nm.deleted = FALSE
    AND nte.id IS NOT NULL
GROUP BY nm.notebook_uuid, nm.visible_name, nm.last_opened, sr.status
HAVING total_characters > 1000  -- Only notebooks with substantial content
ORDER BY total_characters DESC
LIMIT 15;

-- ===========================================
-- 8. RECENT ACTIVITY ANALYSIS
-- ===========================================

-- What has been active recently but might need sync
SELECT
    'RECENT_ACTIVITY' as report,
    nm.visible_name,
    nm.notebook_uuid,
    datetime(CAST(nm.last_opened AS INTEGER) / 1000, 'unixepoch') as last_opened_readable,
    datetime(CAST(nm.last_modified AS INTEGER) / 1000, 'unixepoch') as last_modified_readable,
    COUNT(nte.id) as page_count,
    MAX(nte.updated_at) as last_content_update,
    sr.synced_at as last_notion_sync,
    CASE
        WHEN sr.id IS NULL THEN 'NEVER_SYNCED'
        WHEN sr.synced_at < MAX(nte.updated_at) THEN 'CONTENT_NEWER_THAN_SYNC'
        WHEN sr.status = 'success' THEN 'UP_TO_DATE'
        ELSE sr.status
    END as sync_analysis
FROM notebook_metadata nm
LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
    AND nte.text IS NOT NULL AND LENGTH(nte.text) > 0
LEFT JOIN sync_records sr ON (
    sr.item_id = nm.notebook_uuid
    AND sr.target_name = 'notion'
    AND sr.item_type = 'notebook'
    AND sr.status = 'success'
)
WHERE nm.deleted = FALSE
    AND nm.last_opened IS NOT NULL
    AND CAST(nm.last_opened AS INTEGER) > (strftime('%s', 'now') - 7*24*60*60) * 1000  -- Last 7 days
GROUP BY nm.notebook_uuid, nm.visible_name, nm.last_opened, nm.last_modified, sr.synced_at, sr.status
ORDER BY CAST(nm.last_opened AS INTEGER) DESC;

-- ===========================================
-- 9. SPECIFIC NOTEBOOK ANALYSIS (Replace UUID)
-- ===========================================

-- Detailed analysis for a specific notebook (replace with actual UUID)
-- Example: Markus notebook analysis
/*
SELECT
    'NOTEBOOK_DETAIL' as report,
    nm.visible_name,
    nm.notebook_uuid,
    nm.full_path,
    datetime(CAST(nm.last_opened AS INTEGER) / 1000, 'unixepoch') as last_opened_readable,
    datetime(CAST(nm.last_modified AS INTEGER) / 1000, 'unixepoch') as last_modified_readable,
    COUNT(nte.id) as page_count,
    SUM(LENGTH(nte.text)) as total_characters,
    MAX(nte.updated_at) as last_content_update,
    sr.synced_at as last_notion_sync,
    sr.content_hash as last_synced_hash,
    sr.status as sync_status
FROM notebook_metadata nm
LEFT JOIN notebook_text_extractions nte ON nm.notebook_uuid = nte.notebook_uuid
LEFT JOIN sync_records sr ON (
    sr.item_id = nm.notebook_uuid
    AND sr.target_name = 'notion'
    AND sr.item_type = 'notebook'
)
WHERE nm.notebook_uuid = 'YOUR_NOTEBOOK_UUID_HERE'  -- Replace with actual UUID
GROUP BY nm.notebook_uuid, nm.visible_name, nm.full_path, nm.last_opened, nm.last_modified, sr.synced_at, sr.content_hash, sr.status;
*/