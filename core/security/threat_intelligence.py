#!/usr/bin/env python3
"""
Threat Intelligence Engine - Multi-Source Threat Intelligence Integration
Aggregates threat data from AbuseIPDB, OTX AlienVault, VirusTotal, and internal sources
"""

import asyncio
import hashlib
import time
import logging
import os
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import ipaddress
import json

import aiohttp
import requests
try:
    from OTXv2 import OTX  # type: ignore
except ImportError:
    OTX = None  # type: ignore
from ipwhois import IPWhois

from .active_defense_types import (
    ThreatIntelligence, ThreatIntelSource, ThreatConfidence,
    AttackType, calculate_threat_score
)

logger = logging.getLogger(__name__)


class ThreatIntelligenceEngine:
    """
    Multi-source threat intelligence aggregation and analysis engine
    Production-ready with real API integrations
    """
    
    def __init__(
        self,
        abuseipdb_key: Optional[str] = None,
        virustotal_key: Optional[str] = None,
        otx_key: Optional[str] = None,
        enable_caching: bool = True,
        cache_ttl_seconds: int = 3600
    ):
        self.logger = logging.getLogger(f"{__name__}.ThreatIntelligenceEngine")
        
        # API Keys
        self.abuseipdb_key = abuseipdb_key
        self.virustotal_key = virustotal_key
        self.otx_key = otx_key
        
        # Initialize OTX client if key provided
        self.otx_client = OTX(otx_key) if (otx_key and OTX is not None) else None  # type: ignore
        
        # Cache configuration
        self.enable_caching = enable_caching
        self.cache_ttl = cache_ttl_seconds
        self.intel_cache: Dict[str, ThreatIntelligence] = {}
        self.cache_timestamps: Dict[str, float] = {}

        persistence_env = os.getenv("TORINAI_THREAT_INTEL_PERSISTENCE", "true").strip().lower()
        self._persistence_enabled = persistence_env not in {"0", "false", "no", "off"}
        self._persistence_table_ready = False
        
        # Statistics
        self.stats = {
            "queries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "abuseipdb_queries": 0,
            "virustotal_queries": 0,
            "otx_queries": 0,
            "whois_queries": 0,
            "threats_detected": 0,
            "high_confidence_threats": 0
        }
        
        # Internal threat database
        self.internal_threats: Dict[str, ThreatIntelligence] = {}
        
        self.logger.info("Threat Intelligence Engine initialized")

    async def load_persisted_state(self) -> Dict[str, int]:
        """Best-effort restore of threat intel cache and internal threats after restart."""
        if not self._persistence_enabled:
            return {"cache": 0, "internal": 0}

        db = await self._get_db_optional()
        if db is None:
            return {"cache": 0, "internal": 0}

        await self._ensure_persistence_table(db)

        restored_cache = 0
        restored_internal = 0
        try:
            rows = await db.execute_query(
                """
                SELECT
                    ip,
                    kind,
                    intel,
                    EXTRACT(EPOCH FROM cached_at) AS cached_at_epoch
                FROM threat_intel_state
                WHERE (expires_at IS NULL OR expires_at > NOW())
                """.strip(),
                fetch_all=True,
            )
        except Exception as e:
            self.logger.warning(f"Threat intel persistence: restore query failed: {e}")
            return {"cache": 0, "internal": 0}

        for row in rows or []:
            try:
                ip = row.get("ip")
                kind = row.get("kind")
                intel_payload = row.get("intel")
                cached_at_epoch = row.get("cached_at_epoch")

                intel = self._intel_from_json(ip, intel_payload)
                if kind == "internal":
                    self.internal_threats[ip] = intel
                    restored_internal += 1
                else:
                    self.intel_cache[ip] = intel
                    try:
                        self.cache_timestamps[ip] = float(cached_at_epoch) if cached_at_epoch is not None else time.time()
                    except Exception:
                        self.cache_timestamps[ip] = time.time()
                    restored_cache += 1
            except Exception:
                continue

        if restored_cache or restored_internal:
            self.logger.info(
                f"Threat intel persistence: restored cache={restored_cache}, internal={restored_internal}"
            )

        return {"cache": restored_cache, "internal": restored_internal}
    
    async def get_ip_intelligence(
        self,
        ip_address: str,
        sources: Optional[List[ThreatIntelSource]] = None
    ) -> ThreatIntelligence:
        """
        Get comprehensive threat intelligence for an IP address
        
        Args:
            ip_address: IP address to analyze
            sources: List of sources to query (None = all available)
        
        Returns:
            ThreatIntelligence object with aggregated data
        """
        self.stats["queries"] += 1
        
        # Validate IP
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            self.logger.error(f"Invalid IP address: {ip_address}")
            return self._create_empty_intelligence(ip_address)
        
        # Check cache
        if self.enable_caching and ip_address in self.intel_cache:
            cache_age = time.time() - self.cache_timestamps.get(ip_address, 0)
            if cache_age < self.cache_ttl:
                self.stats["cache_hits"] += 1
                self.logger.debug(f"Cache hit for {ip_address} (age: {cache_age:.0f}s)")
                return self.intel_cache[ip_address]
        
        self.stats["cache_misses"] += 1
        
        # Determine sources to query
        if sources is None:
            sources = self._get_available_sources()
        
        # Query all sources in parallel
        tasks = []
        if ThreatIntelSource.ABUSEIPDB in sources and self.abuseipdb_key:
            tasks.append(self._query_abuseipdb(ip_address))
        if ThreatIntelSource.VIRUSTOTAL in sources and self.virustotal_key:
            tasks.append(self._query_virustotal(ip_address))
        if ThreatIntelSource.OTX_ALIENVAULT in sources and self.otx_client:
            tasks.append(self._query_otx(ip_address))
        if ThreatIntelSource.INTERNAL in sources:
            tasks.append(self._query_internal(ip_address))
        
        # Always get WHOIS data
        tasks.append(self._query_whois(ip_address))
        
        # Gather all results
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and keep only valid results
        results = [result for result in raw_results if isinstance(result, dict)]
        
        # Aggregate intelligence
        intel = self._aggregate_intelligence(ip_address, results, sources)
        
        # Cache result
        if self.enable_caching:
            self.intel_cache[ip_address] = intel
            self.cache_timestamps[ip_address] = time.time()

            if self._persistence_enabled:
                persist_all = os.getenv("TORINAI_THREAT_INTEL_PERSIST_ALL", "false").strip().lower() in {"1", "true", "yes", "on"}
                if persist_all or intel.reputation_score >= 0.5 or intel.confidence in {ThreatConfidence.HIGH, ThreatConfidence.CRITICAL}:
                    await self._persist_intel(ip_address, intel, kind="cache", ttl_seconds=self.cache_ttl)

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
                CREATE TABLE IF NOT EXISTS threat_intel_state (
                    ip TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    intel JSONB NOT NULL,
                    cached_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ,
                    PRIMARY KEY (ip, kind)
                )
                """.strip(),
            )
            await db.execute_query(
                "CREATE INDEX IF NOT EXISTS idx_threat_intel_state_expires ON threat_intel_state (expires_at)".strip(),
            )
            self._persistence_table_ready = True
        except Exception as e:
            self.logger.warning(f"Threat intel persistence: failed to ensure table: {e}")

    def _intel_to_json(self, intel: ThreatIntelligence) -> Dict[str, Any]:
        def _safe_raw(value: Any) -> Any:
            try:
                json.dumps(value)
                return value
            except Exception:
                return str(value)

        raw_data = _safe_raw(intel.raw_data)
        if isinstance(raw_data, dict):
            raw_data = {str(k): _safe_raw(v) for k, v in raw_data.items()}

        return {
            "intel_id": intel.intel_id,
            "ip_address": intel.ip_address,
            "reputation_score": float(intel.reputation_score),
            "confidence": getattr(intel.confidence, "value", str(intel.confidence)),
            "sources": [getattr(s, "value", str(s)) for s in (intel.sources or [])],
            "threat_types": [getattr(t, "value", str(t)) for t in (intel.threat_types or [])],
            "first_seen": float(intel.first_seen),
            "last_seen": float(intel.last_seen),
            "report_count": int(intel.report_count),
            "country": intel.country,
            "asn": intel.asn,
            "isp": intel.isp,
            "categories": list(intel.categories or []),
            "raw_data": raw_data if isinstance(raw_data, (dict, list, str, int, float, bool)) or raw_data is None else str(raw_data),
        }

    def _intel_from_json(self, ip_address: str, payload: Any) -> ThreatIntelligence:
        if not isinstance(payload, dict):
            return self._create_empty_intelligence(ip_address)

        confidence_raw = payload.get("confidence")
        try:
            confidence = ThreatConfidence(confidence_raw)
        except Exception:
            confidence = ThreatConfidence.LOW

        sources_raw = payload.get("sources") or []
        sources: List[ThreatIntelSource] = []
        for s in sources_raw:
            try:
                sources.append(ThreatIntelSource(s))
            except Exception:
                continue

        threat_types_raw = payload.get("threat_types") or []
        threat_types: List[AttackType] = []
        for t in threat_types_raw:
            try:
                threat_types.append(AttackType(t))
            except Exception:
                continue

        return ThreatIntelligence(
            intel_id=str(payload.get("intel_id") or hashlib.sha256(ip_address.encode()).hexdigest()[:16]),
            ip_address=str(payload.get("ip_address") or ip_address),
            reputation_score=float(payload.get("reputation_score") or 0.0),
            confidence=confidence,
            sources=sources,
            threat_types=threat_types,
            first_seen=float(payload.get("first_seen") or time.time()),
            last_seen=float(payload.get("last_seen") or time.time()),
            report_count=int(payload.get("report_count") or 0),
            country=payload.get("country"),
            asn=payload.get("asn"),
            isp=payload.get("isp"),
            categories=list(payload.get("categories") or []),
            raw_data=payload.get("raw_data") or {},
        )

    async def _persist_intel(
        self,
        ip_address: str,
        intel: ThreatIntelligence,
        kind: str,
        ttl_seconds: Optional[int],
    ) -> None:
        db = await self._get_db_optional()
        if db is None:
            return

        await self._ensure_persistence_table(db)

        payload = self._intel_to_json(intel)
        expires_at: Optional[datetime]
        if ttl_seconds is None:
            expires_at = None
        else:
            expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=int(ttl_seconds))

        try:
            await db.execute_query(
                """
                INSERT INTO threat_intel_state (ip, kind, intel, cached_at, expires_at)
                VALUES ($1, $2, $3, NOW(), $4)
                ON CONFLICT (ip, kind)
                DO UPDATE SET intel = EXCLUDED.intel,
                              cached_at = NOW(),
                              expires_at = EXCLUDED.expires_at
                """.strip(),
                params=[ip_address, kind, payload, expires_at],
            )
        except Exception as e:
            self.logger.debug(f"Threat intel persistence: persist failed for {ip_address}: {e}")

    async def _remove_persisted_intel(self, ip_address: str, kind: str) -> None:
        db = await self._get_db_optional()
        if db is None:
            return

        await self._ensure_persistence_table(db)

        try:
            await db.execute_query(
                "DELETE FROM threat_intel_state WHERE ip = $1 AND kind = $2".strip(),
                params=[ip_address, kind],
            )
        except Exception:
            pass

    async def _clear_persisted_cache(self) -> None:
        db = await self._get_db_optional()
        if db is None:
            return

        await self._ensure_persistence_table(db)

        try:
            await db.execute_query(
                "DELETE FROM threat_intel_state WHERE kind = 'cache'".strip(),
            )
        except Exception:
            pass
        
        # Update statistics
        if intel.reputation_score > 0.5:
            self.stats["threats_detected"] += 1
        if intel.confidence == ThreatConfidence.CRITICAL:
            self.stats["high_confidence_threats"] += 1
        
        return intel
    
    async def _query_abuseipdb(self, ip_address: str) -> Dict[str, Any]:
        """Query AbuseIPDB API"""
        self.stats["abuseipdb_queries"] += 1
        
        url = "https://api.abuseipdb.com/api/v2/check"
        headers = {
            "Key": self.abuseipdb_key,
            "Accept": "application/json"
        }
        params = {
            "ipAddress": ip_address,
            "maxAgeInDays": "90",
            "verbose": ""
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(url, headers=headers, params=params, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "source": ThreatIntelSource.ABUSEIPDB,
                            "success": True,
                            "data": data.get("data", {})
                        }
                    else:
                        self.logger.warning(f"AbuseIPDB query failed: {response.status}")
                        return {"source": ThreatIntelSource.ABUSEIPDB, "success": False}
        except Exception as e:
            self.logger.error(f"AbuseIPDB query error: {e}")
            return {"source": ThreatIntelSource.ABUSEIPDB, "success": False, "error": str(e)}
    
    async def _query_virustotal(self, ip_address: str) -> Dict[str, Any]:
        """Query VirusTotal API"""
        self.stats["virustotal_queries"] += 1
        
        if not self.virustotal_key:
            return {"source": ThreatIntelSource.VIRUSTOTAL, "success": False}
        
        url = f"https://www.virustotal.com/api/v3/ip_addresses/{ip_address}"
        headers = {
            "x-apikey": self.virustotal_key
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=10)
                async with session.get(url, headers=headers, timeout=timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "source": ThreatIntelSource.VIRUSTOTAL,
                            "success": True,
                            "data": data.get("data", {})
                        }
                    else:
                        self.logger.warning(f"VirusTotal query failed: {response.status}")
                        return {"source": ThreatIntelSource.VIRUSTOTAL, "success": False}
        except Exception as e:
            self.logger.error(f"VirusTotal query error: {e}")
            return {"source": ThreatIntelSource.VIRUSTOTAL, "success": False, "error": str(e)}
    
    async def _query_otx(self, ip_address: str) -> Dict[str, Any]:
        """Query OTX AlienVault"""
        self.stats["otx_queries"] += 1
        
        if not self.otx_client or OTX is None:
            return {"source": ThreatIntelSource.OTX_ALIENVAULT, "success": False}
        
        try:
            # OTX client is synchronous, run in executor
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.otx_client.get_indicator_details_full(  # type: ignore
                    OTX.IndicatorTypes.IPv4,  # type: ignore
                    ip_address
                )
            )
            
            return {
                "source": ThreatIntelSource.OTX_ALIENVAULT,
                "success": True,
                "data": result
            }
        except Exception as e:
            self.logger.error(f"OTX query error: {e}")
            return {"source": ThreatIntelSource.OTX_ALIENVAULT, "success": False, "error": str(e)}
    
    async def _query_internal(self, ip_address: str) -> Dict[str, Any]:
        """Query internal threat database"""
        if ip_address in self.internal_threats:
            return {
                "source": ThreatIntelSource.INTERNAL,
                "success": True,
                "data": self.internal_threats[ip_address]
            }
        return {"source": ThreatIntelSource.INTERNAL, "success": False}
    
    async def _query_whois(self, ip_address: str) -> Dict[str, Any]:
        """Query WHOIS for IP information"""
        self.stats["whois_queries"] += 1
        
        try:
            # WHOIS query is blocking, run in executor
            loop = asyncio.get_event_loop()
            whois_data = await loop.run_in_executor(
                None,
                lambda: IPWhois(ip_address).lookup_rdap()
            )
            
            return {
                "source": "whois",
                "success": True,
                "data": whois_data
            }
        except Exception as e:
            self.logger.debug(f"WHOIS query error for {ip_address}: {e}")
            return {"source": "whois", "success": False}
    
    def _aggregate_intelligence(
        self,
        ip_address: str,
        results: List[Dict[str, Any]],
        sources: List[ThreatIntelSource]
    ) -> ThreatIntelligence:
        """Aggregate intelligence from multiple sources"""
        
        intel_id = hashlib.sha256(f"{ip_address}_{time.time()}".encode()).hexdigest()[:16]
        
        reputation_scores = []
        threat_types = set()
        categories = set()
        all_sources = []
        raw_data = {}
        country = None
        asn = None
        isp = None
        report_count = 0
        
        # Process each result
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"Query exception: {result}")
                continue
            
            if not result.get("success"):
                continue
            
            source = result.get("source")
            data = result.get("data", {})
            
            # Process AbuseIPDB data
            if source == ThreatIntelSource.ABUSEIPDB:
                all_sources.append(ThreatIntelSource.ABUSEIPDB)
                abuse_score = data.get("abuseConfidenceScore", 0) / 100.0
                reputation_scores.append(abuse_score)
                report_count += data.get("totalReports", 0)
                
                if abuse_score > 0.5:
                    threat_types.add(AttackType.BOT_ATTACK)
                
                country = data.get("countryCode")
                isp = data.get("isp")
                raw_data["abuseipdb"] = data
            
            # Process VirusTotal data
            elif source == ThreatIntelSource.VIRUSTOTAL:
                all_sources.append(ThreatIntelSource.VIRUSTOTAL)
                attributes = data.get("attributes", {})
                last_analysis = attributes.get("last_analysis_stats", {})
                
                malicious = last_analysis.get("malicious", 0)
                suspicious = last_analysis.get("suspicious", 0)
                total = sum(last_analysis.values()) or 1
                
                vt_score = (malicious * 1.0 + suspicious * 0.5) / total
                reputation_scores.append(vt_score)
                
                if malicious > 0:
                    threat_types.add(AttackType.MALWARE_UPLOAD)
                
                country = country or attributes.get("country")
                asn = attributes.get("asn")
                raw_data["virustotal"] = data
            
            # Process OTX data
            elif source == ThreatIntelSource.OTX_ALIENVAULT:
                all_sources.append(ThreatIntelSource.OTX_ALIENVAULT)
                
                # OTX provides pulses (threat intelligence reports)
                pulses = data.get("general", {}).get("pulse_info", {}).get("pulses", [])
                if pulses:
                    otx_score = min(len(pulses) * 0.1, 1.0)
                    reputation_scores.append(otx_score)
                    
                    for pulse in pulses:
                        tags = pulse.get("tags", [])
                        for tag in tags:
                            if "malware" in tag.lower():
                                threat_types.add(AttackType.MALWARE_UPLOAD)
                            elif "ddos" in tag.lower():
                                threat_types.add(AttackType.DDOS)
                            elif "scan" in tag.lower():
                                threat_types.add(AttackType.PORT_SCAN)
                
                raw_data["otx"] = data
            
            # Process internal data
            elif source == ThreatIntelSource.INTERNAL:
                all_sources.append(ThreatIntelSource.INTERNAL)
                internal_intel = data
                reputation_scores.append(internal_intel.reputation_score)
                threat_types.update(internal_intel.threat_types)
                raw_data["internal"] = data
            
            # Process WHOIS data
            elif source == "whois":
                country = country or data.get("asn_country_code")
                asn = asn or data.get("asn")
                isp = isp or data.get("network", {}).get("name")
                raw_data["whois"] = data
        
        # Calculate aggregate reputation score
        if reputation_scores:
            reputation_score = max(reputation_scores)  # Use highest threat score
        else:
            reputation_score = 0.0
        
        # Determine confidence
        source_count = len(all_sources)
        if source_count >= 3:
            confidence = ThreatConfidence.CRITICAL
        elif source_count == 2:
            confidence = ThreatConfidence.HIGH
        elif source_count == 1:
            confidence = ThreatConfidence.MEDIUM
        else:
            confidence = ThreatConfidence.LOW
        
        # Adjust confidence based on reputation score
        if reputation_score < 0.3:
            confidence = ThreatConfidence.LOW
        elif reputation_score > 0.8 and confidence in [ThreatConfidence.LOW, ThreatConfidence.MEDIUM]:
            confidence = ThreatConfidence.HIGH
        
        # Create ThreatIntelligence object
        now = time.time()
        intel = ThreatIntelligence(
            intel_id=intel_id,
            ip_address=ip_address,
            reputation_score=reputation_score,
            confidence=confidence,
            sources=all_sources,
            threat_types=list(threat_types),
            first_seen=now,
            last_seen=now,
            report_count=report_count,
            country=country,
            asn=asn,
            isp=isp,
            categories=list(categories),
            raw_data=raw_data
        )

        if reputation_score > 0.5:
            try:
                from core.utils.notification_publisher import send_system_notification
                import asyncio
                severity = "critical" if reputation_score > 0.8 else "warning" if reputation_score > 0.6 else "info"
                asyncio.create_task(send_system_notification(
                    title=f"🔍 Threat Identified: {ip_address}",
                    message=f"**IP:** {ip_address}\n**Reputation Score:** {reputation_score:.2f}\n**Confidence:** {confidence.value}\n**Country:** {country or 'Unknown'}\n**Threat Types:** {', '.join([t.value for t in threat_types]) if threat_types else 'None'}\n**Report Count:** {report_count}",
                    severity=severity,
                    metadata={
                        "ip_address": ip_address,
                        "reputation_score": reputation_score,
                        "confidence": confidence.value,
                        "threat_types": [t.value for t in threat_types],
                        "country": country,
                        "report_count": report_count
                    }
                ))
            except:
                pass

        return intel
    
    def _get_available_sources(self) -> List[ThreatIntelSource]:
        """Get list of available threat intelligence sources"""
        sources = [ThreatIntelSource.INTERNAL]
        
        if self.abuseipdb_key:
            sources.append(ThreatIntelSource.ABUSEIPDB)
        if self.virustotal_key:
            sources.append(ThreatIntelSource.VIRUSTOTAL)
        if self.otx_client:
            sources.append(ThreatIntelSource.OTX_ALIENVAULT)
        
        return sources
    
    def _create_empty_intelligence(self, ip_address: str) -> ThreatIntelligence:
        """Create empty intelligence object for invalid IPs"""
        return ThreatIntelligence(
            intel_id=hashlib.sha256(ip_address.encode()).hexdigest()[:16],
            ip_address=ip_address,
            reputation_score=0.0,
            confidence=ThreatConfidence.LOW,
            sources=[],
            threat_types=[],
            first_seen=time.time(),
            last_seen=time.time()
        )
    
    def add_internal_threat(
        self,
        ip_address: str,
        threat_types: List[AttackType],
        reputation_score: float,
        evidence: Optional[Dict[str, Any]] = None
    ):
        """Add IP to internal threat database"""
        intel_id = hashlib.sha256(f"internal_{ip_address}".encode()).hexdigest()[:16]
        
        intel = ThreatIntelligence(
            intel_id=intel_id,
            ip_address=ip_address,
            reputation_score=reputation_score,
            confidence=ThreatConfidence.HIGH,
            sources=[ThreatIntelSource.INTERNAL],
            threat_types=threat_types,
            first_seen=time.time(),
            last_seen=time.time(),
            categories=["internal_detection"],
            raw_data=evidence or {}
        )
        
        self.internal_threats[ip_address] = intel
        self.logger.info(f"Added {ip_address} to internal threat database (score: {reputation_score:.2f})")

        if self._persistence_enabled:
            try:
                asyncio.get_running_loop().create_task(
                    self._persist_intel(ip_address, intel, kind="internal", ttl_seconds=None)
                )
            except RuntimeError:
                pass
    
    def remove_internal_threat(self, ip_address: str) -> bool:
        """Remove IP from internal threat database"""
        if ip_address in self.internal_threats:
            del self.internal_threats[ip_address]
            self.logger.info(f"Removed {ip_address} from internal threat database")

            if self._persistence_enabled:
                try:
                    asyncio.get_running_loop().create_task(
                        self._remove_persisted_intel(ip_address, kind="internal")
                    )
                except RuntimeError:
                    pass
            return True
        return False
    
    def clear_cache(self):
        """Clear intelligence cache"""
        self.intel_cache.clear()
        self.cache_timestamps.clear()
        self.logger.info("Intelligence cache cleared")

        if self._persistence_enabled:
            try:
                asyncio.get_running_loop().create_task(self._clear_persisted_cache())
            except RuntimeError:
                pass
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get engine statistics"""
        cache_size = len(self.intel_cache)
        internal_threats_count = len(self.internal_threats)
        
        return {
            **self.stats,
            "cache_size": cache_size,
            "cache_hit_rate": (
                self.stats["cache_hits"] / max(self.stats["queries"], 1)
            ),
            "internal_threats_count": internal_threats_count,
            "sources_available": len(self._get_available_sources())
        }


def create_threat_intelligence_engine(
    abuseipdb_key: Optional[str] = None,
    virustotal_key: Optional[str] = None,
    otx_key: Optional[str] = None
) -> ThreatIntelligenceEngine:
    """Factory function to create ThreatIntelligenceEngine"""
    return ThreatIntelligenceEngine(
        abuseipdb_key=abuseipdb_key,
        virustotal_key=virustotal_key,
        otx_key=otx_key
    )

