#!/usr/bin/env python3
"""
Test Environment Loader
========================
Test that the global environment loader correctly loads from Dominion Labs .env
"""

import sys
from pathlib import Path

# Add TorinAI to path
sys.path.insert(0, str(Path(__file__).parent))

from core.utils.env_loader import (
    load_global_env,
    get_env,
    get_cloudflare_credentials,
    get_threat_intel_keys,
    get_database_credentials,
    list_available_env_vars,
    GLOBAL_ENV_FILE
)

def test_env_loader():
    """Test environment loader"""
    print("=" * 80)
    print("TESTING GLOBAL ENVIRONMENT LOADER")
    print("=" * 80)

    # Test 1: Check .env file exists
    print(f"\n1. Checking global .env file location...")
    print(f"   Expected: {GLOBAL_ENV_FILE}")
    if GLOBAL_ENV_FILE.exists():
        print(f"   ✅ File exists ({GLOBAL_ENV_FILE.stat().st_size} bytes)")
    else:
        print(f"   ❌ File not found!")
        print(f"   Creating empty .env file...")
        GLOBAL_ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        GLOBAL_ENV_FILE.touch()

    # Test 2: Load environment
    print(f"\n2. Loading global environment...")
    success = load_global_env(force_reload=True)
    if success:
        print(f"   ✅ Environment loaded successfully")
    else:
        print(f"   ⚠️  Environment load had warnings")

    # Test 3: Test Cloudflare credentials
    print(f"\n3. Testing Cloudflare credentials...")
    cf_creds = get_cloudflare_credentials()
    print(f"   API Token: {'***SET***' if cf_creds['api_token'] else 'NOT SET'}")
    print(f"   Zone ID:   {'***SET***' if cf_creds['zone_id'] else 'NOT SET'}")

    # Test 4: Test Threat Intel API keys
    print(f"\n4. Testing Threat Intelligence API keys...")
    ti_keys = get_threat_intel_keys()
    print(f"   AbuseIPDB:  {'***SET***' if ti_keys['abuseipdb_key'] else 'NOT SET'}")
    print(f"   VirusTotal: {'***SET***' if ti_keys['virustotal_key'] else 'NOT SET'}")
    print(f"   OTX:        {'***SET***' if ti_keys['otx_key'] else 'NOT SET'}")

    # Test 5: Test Database credentials
    print(f"\n5. Testing Database credentials...")
    db_creds = get_database_credentials()
    print(f"   Host:     {db_creds['host']}")
    print(f"   Port:     {db_creds['port']}")
    print(f"   User:     {db_creds['user']}")
    print(f"   Password: {'***SET***' if db_creds['password'] else 'NOT SET'}")
    print(f"   Database: {db_creds['database']}")

    # Test 6: Test custom environment variables
    print(f"\n6. Testing custom get_env() function...")
    test_var = get_env('PATH', default='NOT_FOUND')
    print(f"   PATH: {test_var[:50]}..." if len(test_var) > 50 else f"   PATH: {test_var}")

    required_test = False
    try:
        get_env('NONEXISTENT_REQUIRED_VAR', required=True)
    except ValueError as e:
        print(f"   ✅ Required variable check works: {e}")
        required_test = True

    if not required_test:
        print(f"   ❌ Required variable check failed!")

    # Test 7: List all environment variables
    print(f"\n7. Listing all loaded environment variables...")
    env_vars = list_available_env_vars()

    # Filter for Dominion Labs and TorinAI related vars
    dominion_vars = [v for v in env_vars if 'DOMINION' in v[0] or 'TORIN' in v[0]]
    cloudflare_vars = [v for v in env_vars if 'CLOUDFLARE' in v[0]]
    security_vars = [v for v in env_vars if any(k in v[0] for k in ['ABUSEIPDB', 'VIRUSTOTAL', 'OTX', 'API_KEY'])]
    db_vars = [v for v in env_vars if 'DB_' in v[0]]

    print(f"\n   Total environment variables: {len(env_vars)}")

    if dominion_vars:
        print(f"\n   Dominion Labs / TorinAI variables ({len(dominion_vars)}):")
        for key, value in dominion_vars:
            print(f"      {key}: {value}")

    if cloudflare_vars:
        print(f"\n   Cloudflare variables ({len(cloudflare_vars)}):")
        for key, value in cloudflare_vars:
            print(f"      {key}: {value}")

    if security_vars:
        print(f"\n   Security API keys ({len(security_vars)}):")
        for key, value in security_vars:
            print(f"      {key}: {value}")

    if db_vars:
        print(f"\n   Database variables ({len(db_vars)}):")
        for key, value in db_vars:
            print(f"      {key}: {value}")

    # Test 8: Verify no conflicts
    print(f"\n8. Checking for environment conflicts...")
    import os
    env_loaded_marker = os.getenv('DOMINION_ENV_LOADED')
    if env_loaded_marker:
        print(f"   ✅ Environment loaded marker set: {env_loaded_marker}")
    else:
        print(f"   ❌ Environment loaded marker not set!")

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    checks = {
        'Global .env file exists': GLOBAL_ENV_FILE.exists(),
        'Environment loaded': success,
        'Cloudflare credentials available': cf_creds['api_token'] is not None,
        'Threat intel keys available': any(ti_keys.values()),
        'Database config available': db_creds['password'] is not None,
        'Required variable validation works': required_test,
        'Environment marker set': env_loaded_marker is not None
    }

    for check, passed in checks.items():
        status = "✅" if passed else "⚠️ "
        print(f"{status} {check}")

    passed = sum(checks.values())
    total = len(checks)
    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\n🎉 All tests passed! Environment loader is working correctly.")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed or have warnings.")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_env_loader()
