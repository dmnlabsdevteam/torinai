#!/usr/bin/env python3
"""
Cloudflare WAF Manager - Dynamic WAF Rule Management via Cloudflare API
Manages firewall rules, rate limiting, IP access rules, and zone lockdown
"""

import asyncio
import hashlib
import time
import logging
import os
from typing import Dict, Any, List, Optional, Set
from datetime import datetime

import aiohttp

from .active_defense_types import (
    WAFRule, WAFRuleMode, BlockedEntity, AttackType, DefenseAction
)

logger = logging.getLogger(__name__)


class CloudflareWAFManager:
    """
    Production-ready Cloudflare WAF integration for dynamic security rule management
    Uses Cloudflare API v4 for comprehensive WAF control
    """
    
    def __init__(
        self,
        api_token: str,
        zone_id: str,
        account_id: Optional[str] = None
    ):
        self.logger = logging.getLogger(f"{__name__}.CloudflareWAFManager")
        
        # Cloudflare credentials
        self.api_token = api_token
        self.zone_id = zone_id
        self.account_id = account_id
        
        # API endpoints
        self.api_base = "https://api.cloudflare.com/client/v4"
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

        # SSL verification (secure by default)
        verify_env = os.getenv("CLOUDFLARE_VERIFY_SSL", os.getenv("TORINAI_CLOUDFLARE_VERIFY_SSL", "true"))
        self.verify_ssl = str(verify_env).strip().lower() not in {"0", "false", "no", "off"}
        if not self.verify_ssl:
            self.logger.warning(
                "⚠️ Cloudflare SSL verification DISABLED via CLOUDFLARE_VERIFY_SSL. "
                "This is insecure and should only be used for temporary debugging."
            )
        
        # Track managed rules
        self.active_waf_rules: Dict[str, WAFRule] = {}
        self.blocked_ips: Set[str] = set()
        self.rate_limited_ips: Set[str] = set()
        
        # Statistics
        self.stats = {
            "waf_rules_created": 0,
            "waf_rules_deleted": 0,
            "ips_blocked": 0,
            "ips_unblocked": 0,
            "rate_limits_applied": 0,
            "api_calls": 0,
            "api_errors": 0
        }
        
        self.logger.info(f"Cloudflare WAF Manager initialized for zone {zone_id}")
    
    async def block_ip(
        self,
        ip_address: str,
        reason: str = "Security threat",
        mode: WAFRuleMode = WAFRuleMode.BLOCK
    ) -> bool:
        """
        Block an IP address using Cloudflare firewall rules
        
        Args:
            ip_address: IP to block
            reason: Reason for blocking
            mode: Block mode (BLOCK, CHALLENGE, etc.)
        
        Returns:
            True if successful
        """
        if ip_address in self.blocked_ips:
            self.logger.debug(f"IP {ip_address} already blocked in Cloudflare")
            return True
        
        # Create Cloudflare firewall rule expression
        expression = f'(ip.src eq {ip_address})'
        
        rule_id = hashlib.sha256(f"cf_block_{ip_address}_{time.time()}".encode()).hexdigest()[:16]
        
        waf_rule = WAFRule(
            rule_id=rule_id,
            zone_id=self.zone_id,
            description=f"TorinAI Block: {reason}",
            expression=expression,
            action=mode,
            priority=1,  # High priority
            enabled=True
        )
        
        # Create rule via Cloudflare API
        success = await self._create_firewall_rule(waf_rule)
        
        if success:
            self.active_waf_rules[rule_id] = waf_rule
            self.blocked_ips.add(ip_address)
            self.stats["waf_rules_created"] += 1
            self.stats["ips_blocked"] += 1
            self.logger.info(f"Blocked IP {ip_address} in Cloudflare: {reason}")

            try:
                from core.utils.notification_publisher import send_system_notification
                import asyncio
                asyncio.create_task(send_system_notification(
                    title=f"🌐 Cloudflare WAF Rule Created",
                    message=f"**IP:** {ip_address}\n**Action:** {mode.value}\n**Reason:** {reason}\n**Total Rules:** {self.stats['waf_rules_created']}\n**Total Blocked:** {self.stats['ips_blocked']}",
                    severity="info",
                    metadata={
                        "ip_address": ip_address,
                        "action": mode.value,
                        "reason": reason,
                        "rule_id": rule_id
                    }
                ))
            except:
                pass

            return True
        
        return False
    
    async def unblock_ip(self, ip_address: str) -> bool:
        """Unblock an IP address"""
        if ip_address not in self.blocked_ips:
            self.logger.debug(f"IP {ip_address} not currently blocked in Cloudflare")
            return True
        
        # Find rules for this IP
        rules_to_remove = [
            rule_id for rule_id, rule in self.active_waf_rules.items()
            if ip_address in rule.expression
        ]
        
        success = True
        for rule_id in rules_to_remove:
            rule = self.active_waf_rules[rule_id]
            
            if await self._delete_firewall_rule(rule):
                del self.active_waf_rules[rule_id]
                self.stats["waf_rules_deleted"] += 1
            else:
                success = False
        
        if success:
            self.blocked_ips.discard(ip_address)
            self.stats["ips_unblocked"] += 1
            self.logger.info(f"Unblocked IP {ip_address} in Cloudflare")
        
        return success
    
    async def block_country(
        self,
        country_code: str,
        reason: str = "Geo-blocking",
        mode: WAFRuleMode = WAFRuleMode.CHALLENGE
    ) -> bool:
        """
        Block entire country using Cloudflare IP Access Rules API

        Args:
            country_code: ISO country code (e.g., "CN", "RU")
            reason: Reason for blocking
            mode: Block mode (challenge is more compatible across plans)

        Returns:
            True if successful
        """
        try:
            # Use IP Access Rules API which supports country blocking on all plans
            connector = aiohttp.TCPConnector(
                family=0,
                ssl=self.verify_ssl,
                force_close=True,
                enable_cleanup_closed=True
            )

            timeout = aiohttp.ClientTimeout(
                total=45,
                connect=15,
                sock_connect=15,
                sock_read=15
            )

            # Cloudflare IP Access Rules endpoint
            url = f"{self.api_base}/zones/{self.zone_id}/firewall/access_rules/rules"

            payload = {
                "mode": "block",  # challenge, block, whitelist, js_challenge
                "configuration": {
                    "target": "country",
                    "value": country_code.upper()
                },
                "notes": f"TorinAI: {reason}"
            }

            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=timeout,
                    ssl=self.verify_ssl
                ) as response:
                    self.stats["api_calls"] += 1

                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            rule_id = data["result"]["id"]
                            self.logger.info(f"Blocked country {country_code} via IP Access Rules: {rule_id}")
                            return True
                        else:
                            errors = data.get("errors", [])
                            self.logger.error(f"Country blocking failed: {errors}")
                            self.stats["api_errors"] += 1
                            return False
                    else:
                        error_text = await response.text()
                        self.logger.error(f"Country blocking HTTP {response.status}: {error_text}")
                        self.stats["api_errors"] += 1
                        return False

        except Exception as e:
            self.logger.error(f"Country blocking exception: {e}")
            self.stats["api_errors"] += 1
            return False
    
    async def create_rate_limit_rule(
        self,
        ip_address: Optional[str] = None,
        path: Optional[str] = None,
        requests_per_minute: int = 100,
        action: WAFRuleMode = WAFRuleMode.CHALLENGE
    ) -> bool:
        """
        Create rate limiting rule
        
        Args:
            ip_address: Specific IP to rate limit (None = all)
            path: URL path to rate limit (None = all)
            requests_per_minute: Request threshold
            action: Action to take when exceeded
        
        Returns:
            True if successful
        """
        # Build expression
        expressions = []
        if ip_address:
            expressions.append(f'(ip.src eq {ip_address})')
        if path:
            expressions.append(f'(http.request.uri.path eq "{path}")')
        
        expression = " and ".join(expressions) if expressions else "(ip.src ne 0.0.0.0)"
        
        rule_id = hashlib.sha256(f"cf_ratelimit_{time.time()}".encode()).hexdigest()[:16]
        
        waf_rule = WAFRule(
            rule_id=rule_id,
            zone_id=self.zone_id,
            description=f"TorinAI Rate Limit: {requests_per_minute}/min",
            expression=expression,
            action=action,
            priority=10,
            enabled=True,
            metadata={"rate_limit": requests_per_minute}
        )
        
        success = await self._create_firewall_rule(waf_rule)
        
        if success:
            self.active_waf_rules[rule_id] = waf_rule
            self.stats["rate_limits_applied"] += 1
            if ip_address:
                self.rate_limited_ips.add(ip_address)
            self.logger.info(f"Created rate limit rule: {requests_per_minute}/min")
        
        return success
    
    async def create_custom_waf_rule(
        self,
        expression: str,
        description: str,
        action: WAFRuleMode,
        priority: int = 50
    ) -> Optional[str]:
        """
        Create custom WAF rule with advanced Cloudflare expression
        
        Args:
            expression: Cloudflare firewall expression
            description: Rule description
            action: Action to take
            priority: Rule priority
        
        Returns:
            Rule ID if successful, None otherwise
        """
        rule_id = hashlib.sha256(f"cf_custom_{time.time()}".encode()).hexdigest()[:16]
        
        waf_rule = WAFRule(
            rule_id=rule_id,
            zone_id=self.zone_id,
            description=f"TorinAI Custom: {description}",
            expression=expression,
            action=action,
            priority=priority,
            enabled=True
        )
        
        success = await self._create_firewall_rule(waf_rule)
        
        if success:
            self.active_waf_rules[rule_id] = waf_rule
            self.stats["waf_rules_created"] += 1
            self.logger.info(f"Created custom WAF rule: {description}")
            return rule_id
        
        return None
    
    async def _create_firewall_rule(self, rule: WAFRule) -> bool:
        """Create firewall rule via Cloudflare API (2-step: filter then rule)"""
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                # Create connector with proper DNS resolution
                connector = aiohttp.TCPConnector(
                    family=0,  # Allow both IPv4 and IPv6
                    ssl=self.verify_ssl,
                    force_close=True,
                    enable_cleanup_closed=True
                )

                timeout = aiohttp.ClientTimeout(
                    total=45,
                    connect=15,
                    sock_connect=15,
                    sock_read=15
                )

                async with aiohttp.ClientSession(connector=connector) as session:
                    # Step 1: Create filter
                    filter_url = f"{self.api_base}/zones/{self.zone_id}/filters"
                    filter_payload = [{
                        "expression": rule.expression,
                        "paused": not rule.enabled,
                        "description": f"{rule.description} (filter)"
                    }]

                    async with session.post(
                        filter_url,
                        headers=self.headers,
                        json=filter_payload,
                        timeout=timeout,
                        ssl=self.verify_ssl
                    ) as response:
                        self.stats["api_calls"] += 1

                        if response.status != 200:
                            error_text = await response.text()
                            self.logger.error(f"Cloudflare filter creation failed: HTTP {response.status}: {error_text}")
                            self.stats["api_errors"] += 1
                            return False

                        data = await response.json()
                        if not data.get("success"):
                            errors = data.get("errors", [])
                            self.logger.error(f"Cloudflare filter API error: {errors}")
                            self.stats["api_errors"] += 1
                            return False

                        # Extract filter ID
                        if not data.get("result") or len(data["result"]) == 0:
                            self.logger.error("No filter ID returned from Cloudflare")
                            self.stats["api_errors"] += 1
                            return False

                        filter_id = data["result"][0]["id"]

                    # Step 2: Create firewall rule referencing the filter
                    rule_url = f"{self.api_base}/zones/{self.zone_id}/firewall/rules"
                    rule_payload = [{
                        "action": rule.action.value,
                        "priority": rule.priority,
                        "description": rule.description,
                        "filter": {
                            "id": filter_id
                        }
                    }]

                    async with session.post(
                        rule_url,
                        headers=self.headers,
                        json=rule_payload,
                        timeout=timeout,
                        ssl=self.verify_ssl
                    ) as response:
                        self.stats["api_calls"] += 1

                        if response.status == 200:
                            data = await response.json()
                            if data.get("success"):
                                # Store Cloudflare rule ID
                                if data.get("result") and len(data["result"]) > 0:
                                    rule.cloudflare_rule_id = data["result"][0].get("id")
                                return True
                            else:
                                errors = data.get("errors", [])
                                self.logger.error(f"Cloudflare rule API error: {errors}")
                                self.stats["api_errors"] += 1
                                return False
                        else:
                            error_text = await response.text()
                            self.logger.error(f"Cloudflare rule creation failed: HTTP {response.status}: {error_text}")
                            self.stats["api_errors"] += 1
                            return False

            except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
                self.logger.warning(f"Connection attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    self.logger.error(f"Cloudflare API connection failed after {max_retries} attempts: {e}")
                    self.stats["api_errors"] += 1
                    return False

            except Exception as e:
                self.logger.error(f"Cloudflare API exception: {e}")
                self.stats["api_errors"] += 1
                return False

        return False
    
    async def _delete_firewall_rule(self, rule: WAFRule) -> bool:
        """Delete firewall rule via Cloudflare API"""
        if not rule.cloudflare_rule_id:
            self.logger.warning(f"No Cloudflare rule ID for {rule.rule_id}")
            return False
        
        url = f"{self.api_base}/zones/{self.zone_id}/firewall/rules/{rule.cloudflare_rule_id}"
        
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=30)
                async with session.delete(
                    url,
                    headers=self.headers,
                    timeout=timeout
                ) as response:
                    self.stats["api_calls"] += 1
                    
                    if response.status == 200:
                        data = await response.json()
                        return data.get("success", False)
                    else:
                        self.logger.error(f"Cloudflare delete failed: HTTP {response.status}")
                        self.stats["api_errors"] += 1
                        return False
        except Exception as e:
            self.logger.error(f"Cloudflare delete exception: {e}")
            self.stats["api_errors"] += 1
            return False
    
    async def enable_zone_lockdown(
        self,
        urls: List[str],
        allowed_ips: List[str]
    ) -> bool:
        """
        Enable zone lockdown for specific URLs (only allow certain IPs)
        
        Args:
            urls: URL patterns to lock down
            allowed_ips: IPs allowed to access
        
        Returns:
            True if successful
        """
        url = f"{self.api_base}/zones/{self.zone_id}/firewall/lockdowns"
        
        payload = {
            "urls": urls,
            "configurations": [{"target": "ip", "value": ip} for ip in allowed_ips],
            "description": "TorinAI Zone Lockdown",
            "paused": False
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=30)
                async with session.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=timeout
                ) as response:
                    self.stats["api_calls"] += 1
                    
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            self.logger.info(f"Enabled zone lockdown for {len(urls)} URLs")
                            return True
                    
                    self.stats["api_errors"] += 1
                    return False
        except Exception as e:
            self.logger.error(f"Zone lockdown error: {e}")
            self.stats["api_errors"] += 1
            return False
    
    async def get_firewall_events(
        self,
        limit: int = 100,
        action: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent firewall events from Cloudflare
        
        Args:
            limit: Maximum events to retrieve
            action: Filter by action (block, challenge, etc.)
        
        Returns:
            List of firewall events
        """
        url = f"{self.api_base}/zones/{self.zone_id}/firewall/events"
        
        params: Dict[str, Any] = {"per_page": limit}
        if action:
            params["action"] = action
        
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=30)
                async with session.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=timeout
                ) as response:
                    self.stats["api_calls"] += 1
                    
                    if response.status == 200:
                        data = await response.json()
                        if data.get("success"):
                            return data.get("result", [])
                    
                    return []
        except Exception as e:
            self.logger.error(f"Get firewall events error: {e}")
            return []
    
    async def get_active_rules(self) -> List[WAFRule]:
        """Get all active WAF rules"""
        return list(self.active_waf_rules.values())
    
    async def delete_rule(self, rule_id: str) -> bool:
        """Delete a specific WAF rule"""
        if rule_id not in self.active_waf_rules:
            return False
        
        rule = self.active_waf_rules[rule_id]
        success = await self._delete_firewall_rule(rule)
        
        if success:
            del self.active_waf_rules[rule_id]
            self.stats["waf_rules_deleted"] += 1
        
        return success
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get WAF manager statistics"""
        return {
            **self.stats,
            "active_waf_rules": len(self.active_waf_rules),
            "blocked_ips_count": len(self.blocked_ips),
            "rate_limited_ips_count": len(self.rate_limited_ips),
            "zone_id": self.zone_id
        }
    
    def is_ip_blocked(self, ip_address: str) -> bool:
        """Check if IP is currently blocked"""
        return ip_address in self.blocked_ips


def create_cloudflare_waf_manager(
    api_token: str,
    zone_id: str,
    account_id: Optional[str] = None
) -> CloudflareWAFManager:
    """Factory function to create Cloudflare WAF manager"""
    return CloudflareWAFManager(
        api_token=api_token,
        zone_id=zone_id,
        account_id=account_id
    )
