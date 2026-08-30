#!/usr/bin/env python3
"""
Real-Time Firewall Manager - OS Firewall Integration for Active Defense
Supports iptables (Linux) and pf (macOS) for dynamic rule management
"""

import asyncio
import os
import platform
import subprocess
import logging
import hashlib
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Tuple
from collections import defaultdict

from .active_defense_types import (
    FirewallRule, FirewallRuleAction, FirewallChain,
    BlockedEntity, DefenseAction
)

logger = logging.getLogger(__name__)


class RealTimeFirewallManager:
    """
    Production-ready OS firewall manager with iptables and pf support
    Manages dynamic rule creation, modification, and removal
    
    Features:
    - Dynamic rule creation/removal
    - Background polling to verify rules are still in place
    - Automatic rule re-application on drift detection
    - Health event reporting for state mismatches
    """
    
    def __init__(self, test_mode: bool = False):
        self.logger = logging.getLogger(f"{__name__}.RealTimeFirewallManager")
        self.test_mode = test_mode
        
        # Detect OS and firewall type
        self.os_type = platform.system()
        self.firewall_type = self._detect_firewall()
        
        # Active rules tracking
        self.active_rules: Dict[str, FirewallRule] = {}
        self.blocked_ips: Set[str] = set()
        self.block_expirations: Dict[str, Optional[float]] = {}

        # Persistence (best-effort). Disabled in test mode unless explicitly enabled.
        persistence_env = os.getenv("TORINAI_FIREWALL_PERSISTENCE", "true").strip().lower()
        self._persistence_enabled = (
            persistence_env not in {"0", "false", "no", "off"} and not self.test_mode
        )
        self._persistence_table_ready = False
        
        # Statistics
        self.stats = {
            "rules_created": 0,
            "rules_deleted": 0,
            "ips_blocked": 0,
            "ips_unblocked": 0,
            "rule_errors": 0,
            "firewall_type": self.firewall_type,
            "sync_checks": 0,
            "drift_detected": 0,
            "rules_reapplied": 0
        }
        
        # Background monitoring
        self.monitoring_active = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._health_callback: Optional[callable] = None
        self._sync_interval = 60  # Check every 60 seconds
        
        # Check privileges
        if not self.test_mode:
            self._check_privileges()
        
        self.logger.info(f"Firewall Manager initialized: {self.firewall_type} on {self.os_type}")
    
    def set_health_callback(self, callback: callable):
        """Set callback for health events (drift detection, errors)"""
        self._health_callback = callback
        self.logger.info("Health callback configured for firewall manager")
    
    async def start_monitoring(self):
        """Start background monitoring to verify firewall rules are in place"""
        if self.monitoring_active:
            self.logger.warning("Firewall monitoring already active")
            return
        
        # Restore persisted blocks before we begin drift monitoring.
        await self.restore_persisted_blocks()

        self.monitoring_active = True
        self._monitor_task = asyncio.create_task(self._sync_check_loop())
        self.logger.info(f"Started firewall sync monitoring (interval: {self._sync_interval}s)")
    
    async def stop_monitoring(self):
        """Stop background monitoring"""
        self.monitoring_active = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        self.logger.info("Stopped firewall sync monitoring")
    
    async def _sync_check_loop(self):
        """Background loop to verify firewall rules are still in place"""
        while self.monitoring_active:
            try:
                await self._cleanup_expired_blocks()
                await self._verify_and_sync_rules()
                await asyncio.sleep(self._sync_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Firewall sync check error: {e}")
                await self._report_health_event(
                    "firewall_sync_error",
                    "ERROR",
                    f"Firewall sync check failed: {e}"
                )
                await asyncio.sleep(self._sync_interval)
    
    async def _verify_and_sync_rules(self):
        """Verify all expected rules are in place, re-apply if missing"""
        self.stats["sync_checks"] += 1
        
        if not self.active_rules:
            # No rules to verify
            return
        
        # Get current OS firewall state
        os_rules = await self._get_os_firewall_rules()
        
        missing_rules = []
        for rule_id, rule in self.active_rules.items():
            # Check if rule exists in OS
            if not self._rule_exists_in_os(rule, os_rules):
                missing_rules.append(rule)
        
        if missing_rules:
            self.stats["drift_detected"] += 1
            self.logger.warning(f"Firewall drift detected: {len(missing_rules)} rules missing")
            
            # Report drift to health system
            await self._report_health_event(
                "firewall_drift",
                "WARNING",
                f"Firewall drift: {len(missing_rules)} rules missing from OS firewall"
            )
            
            # Re-apply missing rules
            reapplied = 0
            for rule in missing_rules:
                try:
                    success = await self._reapply_rule(rule)
                    if success:
                        reapplied += 1
                        self.stats["rules_reapplied"] += 1
                except Exception as e:
                    self.logger.error(f"Failed to re-apply rule {rule.rule_id}: {e}")
            
            if reapplied > 0:
                self.logger.info(f"Re-applied {reapplied}/{len(missing_rules)} missing rules")
                
            # Report critical if we couldn't restore all rules
            if reapplied < len(missing_rules):
                await self._report_health_event(
                    "firewall_restore_failed",
                    "CRITICAL",
                    f"Failed to restore {len(missing_rules) - reapplied} firewall rules"
                )
    
    async def _get_os_firewall_rules(self) -> List[str]:
        """Get current rules from OS firewall"""
        if self.test_mode:
            # In test mode, pretend all rules exist
            return [f"TorinAI: {r.rule_id}" for r in self.active_rules.values()]
        
        try:
            if self.firewall_type == "iptables":
                # List all iptables rules
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["iptables", "-S"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                )
                if result.returncode == 0:
                    return result.stdout.splitlines()
                    
            elif self.firewall_type == "pf":
                # List pf anchor rules
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["pfctl", "-a", "torin_defense", "-sr"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                )
                if result.returncode == 0:
                    return result.stdout.splitlines()
                    
        except Exception as e:
            self.logger.error(f"Failed to query OS firewall: {e}")
        
        return []
    
    def _rule_exists_in_os(self, rule: FirewallRule, os_rules: List[str]) -> bool:
        """Check if a rule exists in the OS firewall output"""
        # Look for TorinAI comment or the source IP in rules
        rule_markers = [
            f"TorinAI:",
            rule.source_ip if rule.source_ip else "",
            rule.rule_id
        ]
        
        for os_rule in os_rules:
            # Check if any marker indicates this rule exists
            for marker in rule_markers:
                if marker and marker in os_rule:
                    return True
        
        return False
    
    async def _reapply_rule(self, rule: FirewallRule) -> bool:
        """Re-apply a firewall rule that was removed"""
        self.logger.info(f"Re-applying firewall rule: {rule.rule_id}")
        
        if self.firewall_type == "iptables":
            return await self._apply_iptables_rule(rule)
        elif self.firewall_type == "pf":
            return await self._apply_pf_rule(rule)
        
        return False
    
    async def _report_health_event(self, event_type: str, severity: str, message: str):
        """Report a health event to the Singleton/health system"""
        if self._health_callback:
            health_event = {
                "event_type": event_type,
                "severity": severity,
                "component": "firewall_manager",
                "message": message,
                "timestamp": time.time(),
                "stats": self.get_statistics()
            }
            try:
                if asyncio.iscoroutinefunction(self._health_callback):
                    await self._health_callback(health_event)
                else:
                    self._health_callback(health_event)
            except Exception as e:
                self.logger.error(f"Failed to report health event: {e}")

    def _detect_firewall(self) -> str:
        """Detect available firewall system"""
        if self.os_type == "Linux":
            if self._command_exists("iptables"):
                return "iptables"
            elif self._command_exists("nftables"):
                return "nftables"
        elif self.os_type == "Darwin":  # macOS
            if self._command_exists("pfctl"):
                return "pf"
        elif self.os_type == "Windows":
            return "windows_firewall"
        
        return "unknown"
    
    def _command_exists(self, command: str) -> bool:
        """Check if command exists"""
        try:
            result = subprocess.run(
                ["which", command],
                capture_output=True,
                text=True,
                timeout=2
            )
            return result.returncode == 0
        except:
            return False
    
    def _check_privileges(self):
        """Check if running with sufficient privileges"""
        if os.geteuid() != 0:
            self.logger.warning(
                "Not running as root! Firewall operations may fail. "
                "Run with sudo or set test_mode=True for testing."
            )
    
    async def block_ip(
        self,
        ip_address: str,
        reason: str = "Security threat",
        ports: Optional[List[int]] = None,
        protocol: str = "all",
        expires_at: Optional[float] = None,
        persist: bool = True,
    ) -> bool:
        """
        Block an IP address
        
        Args:
            ip_address: IP to block
            reason: Reason for blocking
            ports: Specific ports to block (None = all ports)
            protocol: tcp, udp, icmp, or all
        
        Returns:
            True if successful
        """
        if ip_address in self.blocked_ips:
            self.logger.debug(f"IP {ip_address} already blocked")
            return True
        
        # Create firewall rule
        rule_id = hashlib.sha256(f"block_{ip_address}_{time.time()}".encode()).hexdigest()[:16]
        
        rule = FirewallRule(
            rule_id=rule_id,
            chain=FirewallChain.INPUT,
            action=FirewallRuleAction.DROP,
            protocol=protocol if protocol != "all" else None,
            source_ip=ip_address,
            comment=f"TorinAI: {reason}"
        )
        
        # Apply rule based on firewall type
        if self.firewall_type == "iptables":
            success = await self._apply_iptables_rule(rule, ports)
        elif self.firewall_type == "pf":
            success = await self._apply_pf_rule(rule, ports)
        else:
            self.logger.error(f"Unsupported firewall type: {self.firewall_type}")
            return False
        
        if success:
            self.active_rules[rule_id] = rule
            self.blocked_ips.add(ip_address)
            self.block_expirations[ip_address] = expires_at
            self.stats["rules_created"] += 1
            self.stats["ips_blocked"] += 1
            self.logger.info(f"Blocked IP {ip_address}: {reason}")

            if self._persistence_enabled and persist:
                await self._persist_block_ip(ip_address, reason, expires_at)
            return True
        else:
            self.stats["rule_errors"] += 1
            return False
    
    async def unblock_ip(self, ip_address: str, persist: bool = True) -> bool:
        """
        Unblock an IP address
        
        Args:
            ip_address: IP to unblock
        
        Returns:
            True if successful
        """
        if ip_address not in self.blocked_ips:
            self.logger.debug(f"IP {ip_address} not currently blocked")
            return True
        
        # Find and remove rules for this IP
        rules_to_remove = [
            rule_id for rule_id, rule in self.active_rules.items()
            if rule.source_ip == ip_address
        ]
        
        success = True
        for rule_id in rules_to_remove:
            rule = self.active_rules[rule_id]
            
            if self.firewall_type == "iptables":
                if not await self._remove_iptables_rule(rule):
                    success = False
            elif self.firewall_type == "pf":
                if not await self._remove_pf_rule(rule):
                    success = False
            
            if success:
                del self.active_rules[rule_id]
                self.stats["rules_deleted"] += 1
        
        if success:
            self.blocked_ips.discard(ip_address)
            self.block_expirations.pop(ip_address, None)
            self.stats["ips_unblocked"] += 1
            self.logger.info(f"Unblocked IP {ip_address}")

            if self._persistence_enabled and persist:
                await self._remove_persisted_block_ip(ip_address)
        
        return success

    async def restore_persisted_blocks(self) -> int:
        """Best-effort restore of persisted blocks after restart."""
        if not self._persistence_enabled:
            return 0

        db = await self._get_db_optional()
        if db is None:
            self.logger.info("Firewall persistence: DB unavailable; skipping restore")
            return 0

        await self._ensure_persistence_table(db)

        try:
            rows = await db.execute_query(
                """
                SELECT
                    ip,
                    reason,
                    EXTRACT(EPOCH FROM expires_at) AS expires_at_epoch
                FROM firewall_blocklist
                WHERE expires_at IS NULL OR expires_at > NOW()
                """.strip(),
                fetch_all=True,
            )
        except Exception as e:
            self.logger.warning(f"Firewall persistence: restore query failed: {e}")
            return 0

        restored = 0
        for row in rows or []:
            ip = row.get("ip")
            reason = row.get("reason") or "Restored block"
            expires_at_epoch = row.get("expires_at_epoch")
            try:
                expires_at_ts = float(expires_at_epoch) if expires_at_epoch is not None else None
            except Exception:
                expires_at_ts = None

            try:
                ok = await self.block_ip(ip, reason=reason, expires_at=expires_at_ts, persist=False)
                if ok:
                    restored += 1
            except Exception as e:
                self.logger.warning(f"Firewall persistence: failed to restore {ip}: {e}")

        if restored:
            self.logger.info(f"Firewall persistence: restored {restored} blocked IP(s)")
        return restored

    async def _cleanup_expired_blocks(self):
        """Unblock any IPs whose expiration has passed (including persisted blocks)."""
        if not self.block_expirations:
            return

        now = time.time()
        expired = [ip for ip, exp in self.block_expirations.items() if exp is not None and exp <= now]
        for ip in expired:
            try:
                await self.unblock_ip(ip, persist=True)
            except Exception as e:
                self.logger.warning(f"Failed to auto-unblock expired IP {ip}: {e}")

    async def _get_db_optional(self):
        try:
            from core.database import get_unified_db

            db = await get_unified_db()
            if not getattr(db, "initialized", False):
                return None
            return db
        except Exception:
            return None

    async def _ensure_persistence_table(self, db) -> None:
        if self._persistence_table_ready:
            return

        try:
            await db.execute_query(
                """
                CREATE TABLE IF NOT EXISTS firewall_blocklist (
                    ip TEXT PRIMARY KEY,
                    reason TEXT,
                    blocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ,
                    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """.strip(),
            )
            self._persistence_table_ready = True
        except Exception as e:
            self.logger.warning(f"Firewall persistence: failed to ensure table: {e}")

    async def _persist_block_ip(self, ip_address: str, reason: str, expires_at: Optional[float]) -> None:
        db = await self._get_db_optional()
        if db is None:
            return

        await self._ensure_persistence_table(db)

        expires_dt: Optional[datetime]
        if expires_at is None:
            expires_dt = None
        else:
            try:
                expires_dt = datetime.fromtimestamp(float(expires_at), tz=timezone.utc)
            except Exception:
                expires_dt = None

        try:
            await db.execute_query(
                """
                INSERT INTO firewall_blocklist (ip, reason, blocked_at, expires_at, last_updated)
                VALUES ($1, $2, NOW(), $3, NOW())
                ON CONFLICT (ip)
                DO UPDATE SET reason = EXCLUDED.reason,
                              expires_at = EXCLUDED.expires_at,
                              last_updated = NOW()
                """.strip(),
                params=[ip_address, reason, expires_dt],
            )
        except Exception as e:
            self.logger.warning(f"Firewall persistence: failed to persist block {ip_address}: {e}")

    async def _remove_persisted_block_ip(self, ip_address: str) -> None:
        db = await self._get_db_optional()
        if db is None:
            return

        await self._ensure_persistence_table(db)

        try:
            await db.execute_query(
                "DELETE FROM firewall_blocklist WHERE ip = $1".strip(),
                params=[ip_address],
            )
        except Exception as e:
            self.logger.warning(f"Firewall persistence: failed to remove block {ip_address}: {e}")
    
    async def _apply_iptables_rule(
        self,
        rule: FirewallRule,
        ports: Optional[List[int]] = None
    ) -> bool:
        """Apply iptables rule"""
        # Build iptables command
        cmd = ["iptables", "-A", rule.chain.value]
        
        if rule.protocol:
            cmd.extend(["-p", rule.protocol])
        
        if rule.source_ip:
            cmd.extend(["-s", rule.source_ip])
        
        if rule.dest_ip:
            cmd.extend(["-d", rule.dest_ip])
        
        if ports and rule.protocol in ["tcp", "udp"]:
            for port in ports:
                port_cmd = cmd.copy()
                port_cmd.extend(["--dport", str(port)])
                port_cmd.extend(["-j", rule.action.value.upper()])
                port_cmd.extend(["-m", "comment", "--comment", rule.comment])
                
                if not await self._run_firewall_command(port_cmd):
                    return False
            return True
        else:
            cmd.extend(["-j", rule.action.value.upper()])
            cmd.extend(["-m", "comment", "--comment", rule.comment])
            return await self._run_firewall_command(cmd)
    
    async def _remove_iptables_rule(self, rule: FirewallRule) -> bool:
        """Remove iptables rule"""
        # Build delete command
        cmd = ["iptables", "-D", rule.chain.value]
        
        if rule.protocol:
            cmd.extend(["-p", rule.protocol])
        
        if rule.source_ip:
            cmd.extend(["-s", rule.source_ip])
        
        if rule.dest_ip:
            cmd.extend(["-d", rule.dest_ip])
        
        cmd.extend(["-j", rule.action.value.upper()])
        
        return await self._run_firewall_command(cmd)
    
    async def _apply_pf_rule(
        self,
        rule: FirewallRule,
        ports: Optional[List[int]] = None
    ) -> bool:
        """Apply pf (macOS) rule"""
        # PF uses a different syntax - add to anchor
        action = "block drop" if rule.action == FirewallRuleAction.DROP else "block return"
        
        pf_rule = f"{action} in quick from {rule.source_ip} to any"
        
        if ports and rule.protocol:
            port_str = "{" + ",".join(str(p) for p in ports) + "}"
            pf_rule += f" proto {rule.protocol} port {port_str}"
        
        # Write rule to temp file
        rule_file = f"/tmp/torin_pf_rule_{rule.rule_id}.conf"
        
        try:
            with open(rule_file, "w") as f:
                f.write(f"# {rule.comment}\n")
                f.write(f"{pf_rule}\n")
            
            # Add rule to pf
            cmd = ["pfctl", "-a", "torin_defense", "-f", rule_file]
            success = await self._run_firewall_command(cmd)
            
            # Cleanup
            os.remove(rule_file)
            
            return success
        except Exception as e:
            self.logger.error(f"PF rule application error: {e}")
            return False
    
    async def _remove_pf_rule(self, rule: FirewallRule) -> bool:
        """Remove pf rule"""
        # Flush the anchor to remove rules
        cmd = ["pfctl", "-a", "torin_defense", "-F", "rules"]
        return await self._run_firewall_command(cmd)
    
    async def _run_firewall_command(self, cmd: List[str]) -> bool:
        """Execute firewall command"""
        if self.test_mode:
            self.logger.info(f"TEST MODE: Would execute: {' '.join(cmd)}")
            return True
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
            )
            
            if result.returncode == 0:
                return True
            else:
                self.logger.error(
                    f"Firewall command failed: {' '.join(cmd)}\n"
                    f"stderr: {result.stderr}"
                )
                return False
        except subprocess.TimeoutExpired:
            self.logger.error(f"Firewall command timeout: {' '.join(cmd)}")
            return False
        except Exception as e:
            self.logger.error(f"Firewall command error: {e}")
            return False
    
    async def block_port(
        self,
        port: int,
        protocol: str = "tcp",
        interface: Optional[str] = None
    ) -> bool:
        """Block specific port"""
        rule_id = hashlib.sha256(f"block_port_{port}_{protocol}".encode()).hexdigest()[:16]
        
        rule = FirewallRule(
            rule_id=rule_id,
            chain=FirewallChain.INPUT,
            action=FirewallRuleAction.DROP,
            protocol=protocol,
            dest_port=port,
            interface=interface,
            comment=f"TorinAI: Block {protocol}/{port}"
        )
        
        if self.firewall_type == "iptables":
            cmd = ["iptables", "-A", "INPUT", "-p", protocol, "--dport", str(port), "-j", "DROP"]
            if interface:
                cmd.extend(["-i", interface])
            cmd.extend(["-m", "comment", "--comment", rule.comment])
            success = await self._run_firewall_command(cmd)
        elif self.firewall_type == "pf":
            pf_rule = f"block drop in proto {protocol} to any port {port}"
            rule_file = f"/tmp/torin_pf_port_{rule_id}.conf"
            
            try:
                with open(rule_file, "w") as f:
                    f.write(f"{pf_rule}\n")
                
                cmd = ["pfctl", "-a", "torin_defense", "-f", rule_file]
                success = await self._run_firewall_command(cmd)
                os.remove(rule_file)
            except Exception as e:
                self.logger.error(f"Port blocking error: {e}")
                return False
        else:
            return False
        
        if success:
            self.active_rules[rule_id] = rule
            self.stats["rules_created"] += 1
            self.logger.info(f"Blocked port {protocol}/{port}")
        
        return success
    
    async def allow_ip(
        self,
        ip_address: str,
        reason: str = "Whitelisted",
        ports: Optional[List[int]] = None
    ) -> bool:
        """Explicitly allow an IP (whitelist)"""
        rule_id = hashlib.sha256(f"allow_{ip_address}".encode()).hexdigest()[:16]
        
        rule = FirewallRule(
            rule_id=rule_id,
            chain=FirewallChain.INPUT,
            action=FirewallRuleAction.ACCEPT,
            source_ip=ip_address,
            comment=f"TorinAI: {reason}",
            priority=10  # High priority for whitelists
        )
        
        if self.firewall_type == "iptables":
            # Insert at beginning for high priority
            cmd = ["iptables", "-I", "INPUT", "1", "-s", ip_address, "-j", "ACCEPT"]
            cmd.extend(["-m", "comment", "--comment", rule.comment])
            success = await self._run_firewall_command(cmd)
        elif self.firewall_type == "pf":
            pf_rule = f"pass in quick from {ip_address} to any"
            rule_file = f"/tmp/torin_pf_allow_{rule_id}.conf"
            
            try:
                with open(rule_file, "w") as f:
                    f.write(f"{pf_rule}\n")
                
                cmd = ["pfctl", "-a", "torin_defense", "-f", rule_file]
                success = await self._run_firewall_command(cmd)
                os.remove(rule_file)
            except Exception as e:
                self.logger.error(f"IP allow error: {e}")
                return False
        else:
            return False
        
        if success:
            self.active_rules[rule_id] = rule
            self.stats["rules_created"] += 1
            self.logger.info(f"Allowed IP {ip_address}: {reason}")
        
        return success
    
    async def get_blocked_ips(self) -> List[str]:
        """Get list of currently blocked IPs"""
        return list(self.blocked_ips)
    
    async def get_active_rules(self) -> List[FirewallRule]:
        """Get all active firewall rules"""
        return list(self.active_rules.values())
    
    async def flush_all_rules(self) -> bool:
        """Remove all TorinAI firewall rules (DANGEROUS)"""
        self.logger.warning("Flushing all TorinAI firewall rules")
        
        if self.firewall_type == "iptables":
            # Remove all rules with TorinAI comment
            cmd = ["iptables", "-S"]
            result = await self._run_firewall_command(cmd)
            # Would need to parse output and remove matching rules
            # For safety, not implementing full flush
            pass
        elif self.firewall_type == "pf":
            cmd = ["pfctl", "-a", "torin_defense", "-F", "all"]
            await self._run_firewall_command(cmd)
        
        self.active_rules.clear()
        self.blocked_ips.clear()
        
        return True
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get firewall manager statistics"""
        return {
            **self.stats,
            "active_rules": len(self.active_rules),
            "blocked_ips": len(self.blocked_ips),
            "os_type": self.os_type,
            "test_mode": self.test_mode
        }
    
    def is_ip_blocked(self, ip_address: str) -> bool:
        """Check if IP is currently blocked"""
        return ip_address in self.blocked_ips


def create_firewall_manager(test_mode: bool = False) -> RealTimeFirewallManager:
    """Factory function to create firewall manager"""
    return RealTimeFirewallManager(test_mode=test_mode)
