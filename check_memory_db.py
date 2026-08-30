#!/usr/bin/env python3
"""Check what's stored in the PostgreSQL memory table"""
import asyncio
import asyncpg

async def check_memory():
    conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        user='torin',
        import os
password = os.getenv("TORIN_PASSWORD"),
        database='torin_memory'
    )
    
    # Check table structure
    print('=== MEMORY TABLE STRUCTURE ===')
    cols = await conn.fetch('''
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'memory_hot'
        ORDER BY ordinal_position
    ''')
    for col in cols:
        print(f'  {col["column_name"]}: {col["data_type"]}')
    
    # Count and recent entries
    print('\n=== MEMORY STATS ===')
    count = await conn.fetchval('SELECT COUNT(*) FROM memory_hot')
    print(f'Total memories: {count}')
    
    # Get recent memories
    print('\n=== RECENT 5 MEMORIES ===')
    recent = await conn.fetch('''
        SELECT memory_id, memory_type, importance_score, confidence_score, 
               LEFT(content::text, 800) as content_preview,
               created_at
        FROM memory_hot 
        ORDER BY created_at DESC 
        LIMIT 5
    ''')
    
    for i, mem in enumerate(recent, 1):
        print(f'\n--- Memory {i} ---')
        print(f'ID: {mem["memory_id"]}')
        print(f'Type: {mem["memory_type"]}')
        print(f'Importance: {mem["importance_score"]}, Confidence: {mem["confidence_score"]}')
        print(f'Created: {mem["created_at"]}')
        print(f'Content: {mem["content_preview"]}')
    
    # Check for any summarization patterns
    print('\n=== CHECKING FOR SUMMARIZATION ===')
    summaries = await conn.fetch('''
        SELECT memory_id, content::text
        FROM memory_hot 
        WHERE content::text ILIKE '%summary%' 
           OR content::text ILIKE '%summariz%'
        ORDER BY created_at DESC
        LIMIT 3
    ''')
    print(f'Found {len(summaries)} memories with summary-related content')
    
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_memory())
