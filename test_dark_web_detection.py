#!/usr/bin/env python3
"""
Real Dark Web Detection Test
Tests actual SSN detection across dark web, paste sites, and breach databases
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.tools.security_tools import AIDigitalFootprintDetectionTool

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


async def test_ssn_detection():
    """
    Real test: Search for SSN across dark web, paste sites, breach databases
    """

    # SSN to search for
    ssn = "382-17-9461"

    logger.info("=" * 80)
    logger.info(f"REAL DARK WEB DETECTION TEST")
    logger.info(f"Searching for SSN: {ssn}")
    logger.info("=" * 80)

    # Initialize the detection tool
    detection_tool = AIDigitalFootprintDetectionTool()

    logger.info("\n🔍 Initializing browser automation engine...")
    logger.info("🌐 Starting web scraping across multiple platforms...")
    logger.info("🕸️  Checking: DuckDuckGo, Reddit, GitHub, paste sites, breach databases")
    logger.info("\n⏳ This will take 30-60 seconds for real web queries...\n")

    # Execute the actual detection
    result = await detection_tool.execute(
        search_query=ssn,
        deep_search=True  # Enable deep search for comprehensive results
    )

    # Print results
    logger.info("\n" + "=" * 80)
    logger.info("DETECTION RESULTS")
    logger.info("=" * 80)

    if result.success:
        output = result.output

        logger.info(f"\n📊 Query: {output.get('query')}")
        logger.info(f"⚠️  Risk Score: {output.get('risk_score', 0)}/100")
        logger.info(f"🔢 Total Matches: {len(output.get('matches', []))}")

        matches = output.get('matches', [])

        if matches:
            logger.info(f"\n🚨 FOUND {len(matches)} EXPOSURES:\n")

            for i, match in enumerate(matches, 1):
                logger.info(f"  [{i}] Platform: {match.get('platform', 'Unknown')}")
                logger.info(f"      Sensitivity: {match.get('sensitivity', 'unknown').upper()}")
                if match.get('url'):
                    logger.info(f"      URL: {match.get('url')}")
                if match.get('title'):
                    logger.info(f"      Title: {match.get('title')}")
                if match.get('description'):
                    logger.info(f"      Description: {match.get('description')[:100]}...")
                logger.info("")

            # Summary by sensitivity
            critical = sum(1 for m in matches if m.get('sensitivity') == 'critical')
            high = sum(1 for m in matches if m.get('sensitivity') == 'high')
            moderate = sum(1 for m in matches if m.get('sensitivity') == 'moderate')

            logger.info(f"📈 Breakdown:")
            logger.info(f"   🔴 Critical: {critical}")
            logger.info(f"   🟠 High: {high}")
            logger.info(f"   🟡 Moderate: {moderate}")

        else:
            logger.info(f"\n✅ No exposures found for SSN: {ssn}")
            logger.info("   This SSN does not appear in publicly accessible sources.")

        # Print metadata
        metadata = result.metadata
        logger.info(f"\n🔧 Detection Method: {metadata.get('method', 'unknown')}")
        logger.info(f"🔑 API Keys Required: {metadata.get('api_keys_required', 'N/A')}")
        logger.info(f"🔎 Deep Search: {metadata.get('deep_search', False)}")

    else:
        logger.error(f"\n❌ Detection failed: {result.error}")
        logger.error(f"   Output: {result.output}")

    logger.info("\n" + "=" * 80)
    logger.info("TEST COMPLETE")
    logger.info("=" * 80)


if __name__ == "__main__":
    logger.info("\n🚀 Starting Real Dark Web Detection Test\n")

    try:
        asyncio.run(test_ssn_detection())
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        logger.error(f"\n\n❌ Test failed with error: {e}", exc_info=True)
        sys.exit(1)
