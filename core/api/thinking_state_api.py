#!/usr/bin/env python3
"""
Thinking State API - Endpoints for archival Worker

Provides HTTP endpoints for the Cloudflare Worker to:
1. Fetch records older than cutoff date for archival
2. Delete archived records from MySQL after successful D1 storage
"""

import logging
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header, Depends
from pydantic import BaseModel, Field

from core.database import get_database_manager

logger = logging.getLogger(__name__)

# API Router
router = APIRouter(prefix="/thinking", tags=["Thinking State Archival"])

# Security
MYSQL_API_SECRET = os.getenv("MYSQL_API_SECRET")


# Request Models
class ArchivalRequest(BaseModel):
    """Request to fetch records for archival"""
    cutoff_date: str = Field(..., description="ISO 8601 timestamp - records before this will be archived")


class DeleteArchivedRequest(BaseModel):
    """Request to delete archived records"""
    cutoff_date: str = Field(..., description="ISO 8601 timestamp - records before this will be deleted")


# Response Models
class ArchivalResponse(BaseModel):
    """Response with records to archive"""
    records: List[Dict[str, Any]]
    count: int
    cutoff_date: str


class DeleteResponse(BaseModel):
    """Response after deleting archived records"""
    deleted_count: int
    cutoff_date: str
    success: bool


# Dependency: Verify API secret
async def verify_api_secret(authorization: str = Header(...)):
    """Verify Bearer token matches MYSQL_API_SECRET"""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization.replace("Bearer ", "")
    if token != MYSQL_API_SECRET:
        raise HTTPException(status_code=401, detail="Invalid API secret")

    return token


@router.post("/archive", response_model=ArchivalResponse)
async def fetch_records_for_archival(
    request: ArchivalRequest,
    _: str = Depends(verify_api_secret)
) -> ArchivalResponse:
    """
    Fetch thinking state records older than cutoff date for archival to D1

    Used by Cloudflare Worker to retrieve records that need to be archived.
    Records are returned but NOT deleted from MySQL (deletion happens after
    successful D1 storage via /delete-archived endpoint).

    Args:
        request: Archival request with cutoff date

    Returns:
        List of thinking state records to archive
    """
    try:
        # Parse cutoff date
        try:
            cutoff_datetime = datetime.fromisoformat(request.cutoff_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cutoff_date format (use ISO 8601)")

        # Get unified database (PostgreSQL)
        db = get_database_manager()

        # Fetch records older than cutoff
        rows = await db.execute_query("""
            SELECT
                id,
                task_id,
                timestamp,
                thinking_duration,
                cognitive_load,
                emotional_valence,
                difficulty_score,
                stress_level,
                reasoning_trace,
                decision_factors,
                thinking_state,
                system_metrics,
                cpu_usage,
                memory_usage,
                success,
                outcome_quality,
                domain,
                task_type,
                metadata
            FROM unified.thinking_states
            WHERE timestamp < $1
            ORDER BY timestamp ASC
        """, (cutoff_datetime,), fetch_all=True)

        # Convert to dict format for JSON serialization
        records = []
        for row in rows:
            record = {
                "id": row[0],
                "task_id": row[1],
                "timestamp": row[2].isoformat() if row[2] else None,
                "thinking_duration": float(row[3]) if row[3] else None,
                "cognitive_load": float(row[4]) if row[4] else None,
                "emotional_valence": float(row[5]) if row[5] else None,
                "difficulty_score": float(row[6]) if row[6] else None,
                "stress_level": row[7],
                "reasoning_trace": row[8],  # JSON string
                "decision_factors": row[9],  # JSON string
                "thinking_state": row[10],  # JSON string
                "system_metrics": row[11],  # JSON string
                "cpu_usage": float(row[12]) if row[12] else None,
                "memory_usage": float(row[13]) if row[13] else None,
                "success": bool(row[14]),
                "outcome_quality": float(row[15]) if row[15] else None,
                "domain": row[16],
                "task_type": row[17],
                "metadata": row[18]  # JSON string
            }
            records.append(record)

        logger.info(f"Fetched {len(records)} records for archival (cutoff: {cutoff_datetime})")

        return ArchivalResponse(
            records=records,
            count=len(records),
            cutoff_date=request.cutoff_date
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching records for archival: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch records: {str(e)}")


@router.post("/delete-archived", response_model=DeleteResponse)
async def delete_archived_records(
    request: DeleteArchivedRequest,
    _: str = Depends(verify_api_secret)
) -> DeleteResponse:
    """
    Delete thinking state records older than cutoff date from MySQL

    Called by Cloudflare Worker AFTER successfully archiving records to D1.
    This maintains 60-day retention in hot storage.

    IMPORTANT: Only call this after confirming D1 archival succeeded!

    Args:
        request: Delete request with cutoff date

    Returns:
        Count of deleted records
    """
    try:
        # Parse cutoff date
        try:
            cutoff_datetime = datetime.fromisoformat(request.cutoff_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid cutoff_date format (use ISO 8601)")

        # Get thinking database
        db = get_database_manager()

        # Delete records older than cutoff
        # First, count records to be deleted
        count_result = await db.execute_query("""
            SELECT COUNT(*) as count
            FROM unified.thinking_states
            WHERE timestamp < $1
        """, (cutoff_datetime,), fetch_all=True)

        delete_count = count_result[0]['count'] if count_result else 0

        # Delete records
        await db.execute_query("""
            DELETE FROM unified.thinking_states
            WHERE timestamp < $1
        """, (cutoff_datetime,), commit=True)

        logger.info(f"Deleted {delete_count} archived records from PostgreSQL (cutoff: {cutoff_datetime})")

        return DeleteResponse(
            deleted_count=delete_count,
            cutoff_date=request.cutoff_date,
            success=True
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting archived records: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete records: {str(e)}")


@router.get("/stats")
async def get_thinking_stats(
    _: str = Depends(verify_api_secret)
) -> Dict[str, Any]:
    """
    Get statistics about thinking state database

    Returns:
        Database statistics including record count, success rate, etc.
    """
    try:
        db = get_database_manager()
        stats = await db.get_stats()

        return {
            "success": True,
            "stats": stats,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error getting thinking stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


# Health check endpoint (no auth required)
@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check for thinking state API"""
    try:
        db = get_database_manager()

        # Quick database check
        await db.execute_query("SELECT 1", fetch_all=True)

        return {
            "status": "healthy",
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
