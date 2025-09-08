# Todo-to-Notion Page Linking Design

## Overview
Create todos in a Notion database that link directly back to the specific notebook page where the todo was found.

## Architecture

### 1. Database Schema Enhancement
Add a new table to store Notion block mappings:

```sql
CREATE TABLE notion_page_blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook_uuid TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    notion_page_id TEXT NOT NULL,  -- The notebook's main Notion page ID
    notion_block_id TEXT NOT NULL, -- The toggle block ID for this specific page
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(notebook_uuid, page_number)
);
```

### 2. Notion Sync Enhancement
Modify `_create_page_toggle_block` and `_update_changed_pages_only` to:
- Capture block IDs when creating page toggles
- Store the mapping in `notion_page_blocks` table
- Update block IDs when pages are recreated

### 3. Todo Database Structure in Notion
Create a new Notion database with properties:
- **Title** (text): The todo text
- **Completed** (checkbox): Todo status
- **Source Notebook** (relation): Link to the notebook page
- **Source Page** (number): Page number within notebook
- **Actual Date** (date): When todo was written
- **Confidence** (number): OCR confidence
- **Link to Source** (url): Direct link to the toggle block

### 4. Link Format
Notion block links use this format:
```
https://www.notion.so/{workspace}/{page_id}#{block_id}
```

This creates a direct link that:
- Opens the notebook page
- Scrolls to and highlights the specific page toggle
- Shows the exact context where the todo was found

## Implementation Steps

1. **Create block mapping table**
2. **Enhance notion_sync.py** to capture and store block IDs
3. **Create todo export function** that generates proper links
4. **Test with sample todos** to verify links work correctly

## Benefits

- **Context preservation**: Click todo → jump to exact source location
- **Bidirectional navigation**: From todo back to full context
- **Better organization**: Todos become actionable references to source material
- **Workflow enhancement**: Review todo in context of original notes

## Example Workflow

1. User writes todo on page 15 of "Christian" notebook
2. OCR extracts: "Kurts Excel ausfüllen" with date 2025-08-21
3. System creates Notion todo with:
   - Title: "Kurts Excel ausfüllen"
   - Date: 2025-08-21
   - Link: `https://notion.so/christian-page#page-15-block-id`
4. User clicks link → jumps to page 15 toggle in Christian notebook
5. User sees full context around the todo