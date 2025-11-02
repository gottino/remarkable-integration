-- Verification queries for actual_date column in todos table

-- 1. Check table schema
PRAGMA table_info(todos);

-- 2. Count todos with actual_date
SELECT 
    COUNT(*) as total_todos,
    COUNT(actual_date) as with_actual_date,
    COUNT(CASE WHEN actual_date IS NOT NULL THEN 1 END) as non_null_dates
FROM todos;

-- 3. Show recent todos with dates
SELECT 
    id,
    substr(text, 1, 50) as todo_text,
    actual_date,
    created_at
FROM todos 
WHERE actual_date >= '2025-08-01'
ORDER BY actual_date DESC
LIMIT 10;

-- 4. Show date distribution
SELECT 
    actual_date,
    COUNT(*) as count
FROM todos 
WHERE actual_date IS NOT NULL
GROUP BY actual_date
ORDER BY actual_date DESC
LIMIT 20;