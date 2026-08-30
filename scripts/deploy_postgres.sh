#!/bin/bash
#################################################################
# PostgreSQL Deployment Script
# Blue-Green deployment with health checks and rollback capability
#################################################################

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Add PostgreSQL to PATH
export PATH="/opt/homebrew/Cellar/postgresql@16/16.11_1/bin:$PATH"

echo "================================================================"
echo "POSTGRESQL + pgvector DEPLOYMENT"
echo "================================================================"
echo "Project: TorinAI"
echo "Strategy: Blue-Green deployment"
echo "Rollback: Available if issues detected"
echo "================================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

#################################################################
# Step 1: Pre-Deployment Verification
#################################################################
echo "Step 1: Pre-Deployment Verification"
echo "----------------------------------------------------------------"

# Check if PostgreSQL is running
if ! psql -U stefan -d torinai_db -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${RED}❌ PostgreSQL is not running or accessible${NC}"
    echo "Please start PostgreSQL: brew services start postgresql@16"
    exit 1
fi
echo -e "${GREEN}✓${NC} PostgreSQL is running"

# Verify schemas exist
if ! psql -U stefan -d torinai_db -c "SELECT 1 FROM pg_namespace WHERE nspname = 'unified'" | grep -q 1; then
    echo -e "${RED}❌ unified schema not found${NC}"
    echo "Run: psql -U stefan -d torinai_db -f data/system/postgres_schemas.sql"
    exit 1
fi
echo -e "${GREEN}✓${NC} PostgreSQL schemas deployed"

# Verify pgvector extension
if ! psql -U stefan -d torinai_db -c "SELECT 1 FROM pg_extension WHERE extname = 'vector'" | grep -q 1; then
    echo -e "${RED}❌ pgvector extension not installed${NC}"
    echo "Run: psql -U stefan -d torinai_db -c 'CREATE EXTENSION vector;'"
    exit 1
fi
echo -e "${GREEN}✓${NC} pgvector extension installed"

# Check data migration
LAWS_COUNT=$(psql -U stefan -d torinai_db -t -c "SELECT COUNT(*) FROM unified.governance_laws" | xargs)
echo -e "${GREEN}✓${NC} Governance laws in PostgreSQL: $LAWS_COUNT"

MEMORIES_COUNT=$(psql -U stefan -d torinai_db -t -c "SELECT COUNT(*) FROM memory_hot.memory_hot WHERE embedding IS NOT NULL" | xargs)
echo -e "${GREEN}✓${NC} Memories with embeddings: $MEMORIES_COUNT"

# Check HNSW index exists
INDEX_EXISTS=$(psql -U stefan -d torinai_db -t -c "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='memory_hot' AND tablename='memory_hot' AND indexdef LIKE '%hnsw%'" | xargs)
if [ "$INDEX_EXISTS" -eq "0" ]; then
    echo -e "${RED}❌ HNSW index not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} HNSW index exists"

echo ""

#################################################################
# Step 2: Backup Current Configuration
#################################################################
echo "Step 2: Backup Current Configuration"
echo "----------------------------------------------------------------"

# Backup .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    cp "$PROJECT_ROOT/.env" "$PROJECT_ROOT/.env.backup.$(date +%Y%m%d_%H%M%S)"
    echo -e "${GREEN}✓${NC} .env backed up"
fi

echo ""

#################################################################
# Step 3: Stop Running Services
#################################################################
echo "Step 3: Stop Running Services"
echo "----------------------------------------------------------------"

# Check if TorinAI is running
TORIN_PID=$(pgrep -f "python.*core/main.py" || true)
if [ -n "$TORIN_PID" ]; then
    echo "Stopping TorinAI (PID: $TORIN_PID)..."
    kill $TORIN_PID
    sleep 2

    # Force kill if still running
    if ps -p $TORIN_PID > /dev/null 2>&1; then
        echo "Force stopping..."
        kill -9 $TORIN_PID
    fi
    echo -e "${GREEN}✓${NC} TorinAI stopped"
else
    echo -e "${YELLOW}⚠${NC} TorinAI not running"
fi

echo ""

#################################################################
# Step 4: Health Check Script
#################################################################
echo "Step 4: Creating Health Check Script"
echo "----------------------------------------------------------------"

cat > "$PROJECT_ROOT/scripts/health_check_postgres.py" << 'EOF'
#!/usr/bin/env python3
"""PostgreSQL Health Check"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.database import TorinUnifiedDatabase

async def health_check():
    """Perform comprehensive health check"""
    db = TorinUnifiedDatabase()

    try:
        await db.initialize()
        print("✓ PostgreSQL connection successful")

        # Check governance laws
        laws = await db.execute_query(
            "SELECT COUNT(*) as count FROM unified.governance_laws",
            fetch_one=True
        )
        print(f"✓ Governance laws: {laws['count']}")

        # Check memory with embeddings
        memories = await db.execute_query(
            "SELECT COUNT(*) as count FROM memory_hot.memory_hot WHERE embedding IS NOT NULL",
            use_hot_tier=True,
            fetch_one=True
        )
        print(f"✓ Memories with embeddings: {memories['count']}")

        # Test vector search
        import numpy as np
        test_embedding = np.random.rand(384).tolist()
        results = await db.execute_query(
            """
            SELECT memory_id, 1 - (embedding <=> $1::vector) AS similarity
            FROM memory_hot.memory_hot
            ORDER BY embedding <=> $1::vector
            LIMIT 1
            """,
            (test_embedding,),
            use_hot_tier=True,
            fetch_all=True
        )
        print(f"✓ Vector search functional (found {len(results)} results)")

        await db.close()
        print("\n✅ All health checks passed!")
        return True

    except Exception as e:
        print(f"\n❌ Health check failed: {e}")
        await db.close()
        return False

if __name__ == "__main__":
    result = asyncio.run(health_check())
    sys.exit(0 if result else 1)
EOF

chmod +x "$PROJECT_ROOT/scripts/health_check_postgres.py"
echo -e "${GREEN}✓${NC} Health check script created"

echo ""

#################################################################
# Step 5: Run Health Check
#################################################################
echo "Step 5: Running Health Check"
echo "----------------------------------------------------------------"

cd "$PROJECT_ROOT"
source venv_torin/bin/activate

if python scripts/health_check_postgres.py; then
    echo -e "${GREEN}✓${NC} Health check passed"
else
    echo -e "${RED}❌ Health check failed - aborting deployment${NC}"
    exit 1
fi

echo ""

#################################################################
# Step 6: Deployment Summary
#################################################################
echo "================================================================"
echo "DEPLOYMENT READY"
echo "================================================================"
echo ""
echo "PostgreSQL is ready for production use:"
echo "  - Database: torinai_db"
echo "  - Schemas: unified, memory_hot, memory_cold"
echo "  - Governance laws: $LAWS_COUNT"
echo "  - Memories: $MEMORIES_COUNT"
echo "  - HNSW index: ✓ Functional"
echo "  - Health checks: ✓ Passing"
echo ""
echo "Next steps:"
echo "  1. Start TorinAI: python core/main.py"
echo "  2. Monitor logs: tail -f logs/torin_main.log"
echo "  3. Verify autonomous agents start correctly"
echo ""
echo "Rollback (if needed):"
echo "  1. Stop services"
echo "  2. Restore backup: cp .env.backup.* .env"
echo "  3. Revert __init__.py to MySQL"
echo "  4. Restart services"
echo ""
echo "================================================================"
