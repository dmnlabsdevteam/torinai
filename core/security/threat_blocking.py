#!/usr/bin/env python3
"""
Threat Blocking Engine - Coordinated Active Defense System
Integrates firewall, WAF, and threat intelligence for real-time blocking
"""

import asyncio
import logging
import time
import hashlib
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
from collections import defaultdict

from .active_defense_types import (
    BlockedEntity, AttackType, DefenseAction, BlockDuration,
    ThreatConfidence, DefensePolicy, DefenseMetrics,
    calculate_threat_score, should_block, determine_block_duration
)
from .threat_intelligence import ThreatIntelligenceEngine
from .firewall_manager import RealTimeFirewallManager
from .cloudflare_waf import CloudflareWAFManager

logger = logging.getLogger(__name__)


class ThreatBlockingEngine:
    """
    Military-grade threat blocking engine coordinating multiple defense layers
    Production-ready with real integrations
    """
    
    def __init__(
        self,
        policy: Optional[DefensePolicy] = None,
        threat_intel: Optional[ThreatIntelligenceEngine] = None,
        firewall_manager: Optional[RealTimeFirewallManager] = None,
        waf_manager: Optional[CloudflareWAFManager] = None
    ):
        self.logger = logging.getLogger(f"{__name__}.ThreatBlockingEngine")
        
        # Defense components
        self.policy = policy or DefensePolicy(
            policy_id="default",
            name="Default Defense Policy"
        )
        self.threat_intel = threat_intel
        self.firewall = firewall_manager
        self.waf = waf_manager
        
        # Blocked entities tracking
        self.blocked_entities: Dict[str, BlockedEntity] = {}
        self.block_history: Dict[str, List[BlockedEntity]] = defaultdict(list)
        
        # Statistics
        self.metrics = DefenseMetrics()
        
        # Background tasks
        self.cleanup_task: Optional[asyncio.Task] = None
        self.monitoring_active = False
        
        self.logger.info(f"Threat Blocking Engine initialized with policy: {self.policy.name}")
    
    async def start_monitoring(self):
        """Start background monitoring and cleanup"""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.cleanup_task = asyncio.create_task(self._cleanup_expired_blocks())
        self.logger.info("Started background monitoring")
    
    async def stop_monitoring(self):
        """Stop background monitoring"""
        self.monitoring_active = False
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Stopped background monitoring")
    
    async def analyze_and_block(
        self,
        ip_address: str,
        attack_type: AttackType,
        evidence: Optional[Dict[str, Any]] = None,
        force_block: bool = False
    ) -> Dict[str, Any]:
        """
        Analyze threat and automatically block if warranted
        
        Args:
            ip_address: IP address to analyze
            attack_type: Type of attack detected
            evidence: Evidence of malicious activity
            force_block: Force blocking regardless of policy
        
        Returns:
            Action result dictionary
        """
        result = {
            "ip_address": ip_address,
            "attack_type": attack_type.value,
            "blocked": False,
            "actions_taken": [],
            "reason": "",
            "threat_score": 0.0
        }
        
        # Check whitelist
        if ip_address in self.policy.whitelisted_ips:
            result["reason"] = "IP is whitelisted"
            self.logger.info(f"Skipping whitelisted IP: {ip_address}")
            return result
        
        # Check blacklist
        blacklist_reason = None
        if ip_address in self.policy.blacklisted_ips:
            force_block = True
            blacklist_reason = "IP is blacklisted"
            result["reason"] = blacklist_reason
        
        # Get threat intelligence if available
        intel = None
        if self.threat_intel and self.policy.use_threat_intel:
            try:
                intel = await self.threat_intel.get_ip_intelligence(ip_address)
                result["threat_intelligence"] = {
                    "reputation_score": intel.reputation_score,
                    "confidence": intel.confidence.value,
                    "sources": [s.value for s in intel.sources],
                    "threat_types": [t.value for t in intel.threat_types]
                }
            except Exception as e:
                self.logger.error(f"Threat intel query failed: {e}")
        
        # Calculate threat score
        previous_blocks = len(self.block_history.get(ip_address, []))
        confidence = intel.confidence if intel else ThreatConfidence.MEDIUM
        
        threat_score = calculate_threat_score(intel, previous_blocks, confidence)
        result["threat_score"] = threat_score
        
        # Determine if should block
        should_block_ip = force_block or should_block(threat_score, self.policy)
        
        if not should_block_ip:
            result["reason"] = f"Threat score {threat_score:.2f} below threshold {self.policy.block_threshold_score}"
            return result
        
        # Determine block duration
        block_duration = determine_block_duration(threat_score, previous_blocks, self.policy)
        
        # Block across all available layers
        actions_taken = []
        
        expires_at_epoch = None
        if block_duration != BlockDuration.PERMANENT:
            expires_at_epoch = time.time() + block_duration.value

        # Layer 1: OS Firewall
        if self.firewall and self.policy.auto_block_enabled:
            try:
                if await self.firewall.block_ip(
                    ip_address,
                    f"Attack: {attack_type.value}",
                    expires_at=expires_at_epoch,
                ):
                    actions_taken.append(DefenseAction.BLOCK_IP)
                    self.logger.info(f"Blocked {ip_address} in OS firewall")
            except Exception as e:
                self.logger.error(f"Firewall block failed: {e}")
        
        # Layer 2: Cloudflare WAF
        if self.waf and self.policy.auto_block_enabled:
            try:
                from .active_defense_types import WAFRuleMode
                waf_mode = WAFRuleMode.BLOCK if threat_score > 0.8 else WAFRuleMode.CHALLENGE
                
                if await self.waf.block_ip(ip_address, f"Attack: {attack_type.value}", waf_mode):
                    action = DefenseAction.BLOCK_IP if waf_mode == WAFRuleMode.BLOCK else DefenseAction.CHALLENGE
                    actions_taken.append(action)
                    self.logger.info(f"Blocked {ip_address} in Cloudflare WAF")
            except Exception as e:
                self.logger.error(f"WAF block failed: {e}")
        
        # Create blocked entity record
        entity_id = hashlib.sha256(f"{ip_address}_{time.time()}".encode()).hexdigest()[:16]
        
        expires_at = expires_at_epoch
        
        blocked_entity = BlockedEntity(
            entity_id=entity_id,
            entity_type="ip",
            entity_value=ip_address,
            reason=blacklist_reason or f"{attack_type.value}: Threat score {threat_score:.2f}",
            attack_type=attack_type,
            blocked_at=time.time(),
            expires_at=expires_at,
            block_count=previous_blocks + 1,
            defense_action=DefenseAction.BLOCK_IP,
            confidence=confidence,
            metadata=evidence or {}
        )
        
        # Track blocked entity
        self.blocked_entities[ip_address] = blocked_entity
        self.block_history[ip_address].append(blocked_entity)
        
        # Update metrics
        self.metrics.total_blocks += 1
        if block_duration == BlockDuration.PERMANENT:
            self.metrics.permanent_blocks += 1
        else:
            self.metrics.temporary_blocks += 1
        
        self.metrics.blocks_by_type[attack_type] = self.metrics.blocks_by_type.get(attack_type, 0) + 1
        
        if intel and intel.country:
            self.metrics.blocks_by_country[intel.country] = self.metrics.blocks_by_country.get(intel.country, 0) + 1
        
        # Update result
        result["blocked"] = True
        result["actions_taken"] = [action.value for action in actions_taken]
        result["block_duration"] = "permanent" if block_duration == BlockDuration.PERMANENT else f"{block_duration.value}s"
        result["reason"] = blocked_entity.reason
        
        self.logger.info(
            f"BLOCKED: {ip_address} | Attack: {attack_type.value} | "
            f"Score: {threat_score:.2f} | Duration: {result['block_duration']}"
        )

        try:
            from core.utils.notification_publisher import send_system_notification
            severity = "critical" if threat_score > 0.9 else "warning"
            await send_system_notification(
                title=f"🛡️ Threat Blocked: {attack_type.value}",
                message=f"**IP:** {ip_address}\n**Threat Score:** {threat_score:.2f}\n**Duration:** {result['block_duration']}\n**Reason:** {blocked_entity.reason}\n**Actions:** {', '.join([a.value for a in actions_taken])}",
                severity=severity,
                metadata={
                    "ip_address": ip_address,
                    "attack_type": attack_type.value,
                    "threat_score": threat_score,
                    "block_duration": result['block_duration'],
                    "block_count": previous_blocks + 1,
                    "country": intel.country if intel else None
                }
            )
        except:
            pass

        return result
    
    async def unblock(self, ip_address: str) -> bool:
        """
        Unblock an IP address across all layers
        
        Args:
            ip_address: IP to unblock
        
        Returns:
            True if successful
        """
        if ip_address not in self.blocked_entities:
            self.logger.debug(f"IP {ip_address} not currently blocked")
            return True
        
        success = True
        
        # Unblock from OS firewall
        if self.firewall:
            try:
                await self.firewall.unblock_ip(ip_address)
            except Exception as e:
                self.logger.error(f"Firewall unblock failed: {e}")
                success = False
        
        # Unblock from Cloudflare WAF
        if self.waf:
            try:
                await self.waf.unblock_ip(ip_address)
            except Exception as e:
                self.logger.error(f"WAF unblock failed: {e}")
                success = False
        
        # Remove from tracking
        if success:
            del self.blocked_entities[ip_address]
            self.logger.info(f"Unblocked {ip_address}")
        
        return success
    
    async def block_country(
        self,
        country_code: str,
        reason: str = "Geo-blocking policy"
    ) -> bool:
        """
        Block entire country (WAF only - OS firewall doesn't support geo-blocking)
        
        Args:
            country_code: ISO country code
            reason: Reason for blocking
        
        Returns:
            True if successful
        """
        if not self.waf:
            self.logger.warning("WAF not available for geo-blocking")
            return False
        
        try:
            success = await self.waf.block_country(country_code, reason)
            
            if success:
                self.policy.blacklisted_countries.add(country_code)
                self.logger.info(f"Blocked country: {country_code}")
            
            return success
        except Exception as e:
            self.logger.error(f"Country blocking failed: {e}")
            return False
    
    async def apply_rate_limit(
        self,
        ip_address: str,
        requests_per_minute: int = 100
    ) -> bool:
        """
        Apply rate limiting to an IP
        
        Args:
            ip_address: IP to rate limit
            requests_per_minute: Request threshold
        
        Returns:
            True if successful
        """
        if not self.waf:
            self.logger.warning("WAF not available for rate limiting")
            return False
        
        try:
            from .active_defense_types import WAFRuleMode
            success = await self.waf.create_rate_limit_rule(
                ip_address=ip_address,
                requests_per_minute=requests_per_minute,
                action=WAFRuleMode.CHALLENGE
            )
            
            if success:
                self.logger.info(f"Applied rate limit to {ip_address}: {requests_per_minute}/min")
            
            return success
        except Exception as e:
            self.logger.error(f"Rate limiting failed: {e}")
            return False
    
    async def _cleanup_expired_blocks(self):
        """Background task to cleanup expired blocks"""
        while self.monitoring_active:
            try:
                now = time.time()
                expired_ips = []
                
                for ip, entity in self.blocked_entities.items():
                    if entity.expires_at and entity.expires_at <= now:
                        expired_ips.append(ip)
                
                # Unblock expired IPs
                for ip in expired_ips:
                    await self.unblock(ip)
                    self.logger.info(f"Auto-unblocked expired block: {ip}")
                
                # Sleep for 60 seconds
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cleanup task error: {e}")
                await asyncio.sleep(60)
    
    def get_blocked_entities(self) -> List[BlockedEntity]:
        """Get all currently blocked entities"""
        return list(self.blocked_entities.values())
    
    def get_block_history(self, ip_address: Optional[str] = None) -> List[BlockedEntity]:
        """Get block history"""
        if ip_address:
            return self.block_history.get(ip_address, [])
        
        # Return all history
        all_history = []
        for history_list in self.block_history.values():
            all_history.extend(history_list)
        return sorted(all_history, key=lambda x: x.blocked_at, reverse=True)
    
    def is_blocked(self, ip_address: str) -> bool:
        """Check if IP is currently blocked"""
        return ip_address in self.blocked_entities
    
    def get_metrics(self) -> DefenseMetrics:
        """Get defense metrics"""
        self.metrics.active_blocks = len(self.blocked_entities)
        self.metrics.last_update = time.time()
        
        # Update component metrics
        if self.firewall:
            self.metrics.firewall_rules_active = len(self.firewall.active_rules)
        if self.waf:
            self.metrics.waf_rules_active = len(self.waf.active_waf_rules)
        
        return self.metrics
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics"""
        metrics = self.get_metrics()
        
        stats = {
            "metrics": {
                "total_blocks": metrics.total_blocks,
                "active_blocks": metrics.active_blocks,
                "temporary_blocks": metrics.temporary_blocks,
                "permanent_blocks": metrics.permanent_blocks,
                "attacks_detected": metrics.attacks_detected,
                "attacks_mitigated": metrics.attacks_mitigated
            },
            "blocks_by_type": dict(metrics.blocks_by_type),
            "blocks_by_country": dict(metrics.blocks_by_country),
            "policy": {
                "name": self.policy.name,
                "auto_block_enabled": self.policy.auto_block_enabled,
                "block_threshold": self.policy.block_threshold_score,
                "rate_limit_threshold": self.policy.rate_limit_threshold
            },
            "components": {
                "threat_intel_available": self.threat_intel is not None,
                "firewall_available": self.firewall is not None,
                "waf_available": self.waf is not None
            }
        }
        
        # Add component stats
        if self.threat_intel:
            stats["threat_intelligence"] = self.threat_intel.get_statistics()
        if self.firewall:
            stats["firewall"] = self.firewall.get_statistics()
        if self.waf:
            stats["waf"] = self.waf.get_statistics()
        
        return stats


def create_threat_blocking_engine(
    policy: Optional[DefensePolicy] = None,
    threat_intel_config: Optional[Dict[str, str]] = None,
    firewall_test_mode: bool = False,
    cloudflare_config: Optional[Dict[str, str]] = None
) -> ThreatBlockingEngine:
    """
    Factory function to create fully integrated threat blocking engine
    
    Args:
        policy: Defense policy configuration
        threat_intel_config: Threat intelligence API keys
        firewall_test_mode: Run firewall in test mode (no actual rules)
        cloudflare_config: Cloudflare API configuration
    
    Returns:
        Configured ThreatBlockingEngine
    """
    # Initialize threat intelligence
    threat_intel = None
    if threat_intel_config:
        from .threat_intelligence import create_threat_intelligence_engine
        threat_intel = create_threat_intelligence_engine(
            abuseipdb_key=threat_intel_config.get("abuseipdb_key"),
            virustotal_key=threat_intel_config.get("virustotal_key"),
            otx_key=threat_intel_config.get("otx_key")
        )
    
    # Initialize firewall manager
    from .firewall_manager import create_firewall_manager
    firewall = create_firewall_manager(test_mode=firewall_test_mode)
    
    # Initialize Cloudflare WAF if configured
    waf = None
    if cloudflare_config and cloudflare_config.get("api_token") and cloudflare_config.get("zone_id"):
        from .cloudflare_waf import create_cloudflare_waf_manager
        waf = create_cloudflare_waf_manager(
            api_token=cloudflare_config["api_token"],
            zone_id=cloudflare_config["zone_id"],
            account_id=cloudflare_config.get("account_id")
        )
    
    return ThreatBlockingEngine(
        policy=policy,
        threat_intel=threat_intel,
        firewall_manager=firewall,
        waf_manager=waf
    )
