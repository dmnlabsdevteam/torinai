-- ============================================================================
-- Create Adaptive Learning Views for Tool Affinity Scoring
-- ============================================================================
-- Run this after the tool_usage_history table has been created
-- These views enable the adaptive learning system to query historical success rates
-- ============================================================================

USE torinai_unified;

-- View: Tool category affinity by intent type
-- Shows success rates for each (intent_type, tool_category) pair
CREATE OR REPLACE VIEW tool_category_affinity AS
SELECT
    intent_type,
    category_name,
    COUNT(*) AS total_uses,
    SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) AS successful_uses,
    ROUND(
        SUM(CASE WHEN success = TRUE THEN 1 ELSE 0 END) / COUNT(*),
        4
    ) AS success_rate,
    AVG(outcome_quality) AS avg_outcome_quality,
    AVG(execution_time_seconds) AS avg_execution_time
FROM tool_usage_history,
JSON_TABLE(
    tool_categories_used,
    '$[*]' COLUMNS(category_name VARCHAR(64) PATH '$')
) AS categories
WHERE completed_at IS NOT NULL
GROUP BY intent_type, category_name
HAVING total_uses >= 3  -- Minimum 3 uses for statistical significance
ORDER BY intent_type, success_rate DESC;

-- View: Recent tool usage patterns
CREATE OR REPLACE VIEW recent_tool_usage AS
SELECT
    usage_id,
    task_id,
    intent_type,
    tool_categories_used,
    success,
    outcome_quality,
    execution_time_seconds,
    started_at,
    completed_at
FROM tool_usage_history
WHERE completed_at IS NOT NULL
ORDER BY completed_at DESC
LIMIT 100;

-- Verify views were created
SELECT 'Views created successfully' AS status;
SELECT COUNT(*) AS tool_usage_records FROM tool_usage_history;
