#!/usr/bin/env python3
"""
TorinAI Main Entry Point
=========================
Primary initialization and orchestration for TorinAI system

CRITICAL INITIALIZATION ORDER (from system_logs analysis):
1. UnifiedLLMService (the teacher model) - MUST BE FIRST
2. Database Systems (PostgreSQL pools, unified database)
3. Memory System (PostgreSQL hot/cold tier storage)
4. Domain Systems (registry, ontology, reasoner, domain master)
5. Learning System (connects to the teacher model)
6. Research & Predictive Intelligence
7. Health Monitoring & Recovery
8. Quantum Computing Systems
9. Autonomous Coordinator (THE SINGLETON)
10. Security & Safety Systems
11. Storage Agents

Features:
- System initialization and configuration
- Service orchestration with proper dependency ordering
- Health monitoring and recovery
- Graceful shutdown handling
- Integration of all core subsystems
"""

import logging
import asyncio
import signal
import sys
import os
import time
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

# Load environment variables
try:
    from dotenv import load_dotenv
    # Load .env.production file if it exists
    env_file = Path(__file__).parent.parent / ".env.production"
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
        print(f"Loaded environment from: {env_file}")
    # Also load .env if it exists (overrides .env.production)
    env_file_local = Path(__file__).parent.parent / ".env"
    if env_file_local.exists():
        load_dotenv(dotenv_path=env_file_local, override=True)
        print(f"Loaded local environment from: {env_file_local}")
except ImportError:
    print("python-dotenv not installed, using system environment variables")

# ============================================================================
# Python Path Configuration
# ============================================================================

# Add parent directory to Python path so we can import core modules
SCRIPT_DIR = Path(__file__).parent.parent.absolute()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# ============================================================================
# Logging Configuration
# ============================================================================

# Create logs directory if it doesn't exist
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/torin_main.log')
    ]
)

# Split the one stream into per-concern channels. ADDITIVE: the stdout stream
# and logs/torin_main.log above are untouched, so anything that greps the main
# log still works -- this is a second way to read the same records.
try:
    from core.observability import channels as _channels
    _channels.install(level=logging.INFO)
except Exception as _chan_err:                     # never block startup on logging
    logging.getLogger(__name__).warning(
        "Channel logging unavailable: %s", _chan_err)

# Every ERROR and CRITICAL onto the canonical failure record. ADDITIVE in the
# same way: the streams above are untouched, and this makes the same records
# QUERYABLE -- 1,113 except-blocks across core/ log a failure and, until this,
# not one of them reached anything a subsystem could ask.
#
# Installed here rather than at each site because a site nobody remembered to
# edit is indistinguishable from a site with nothing to report.
try:
    from core.observability import failure_capture as _failure_capture
    _failure_capture.install()
except Exception as _cap_err:                      # never block startup on logging
    logging.getLogger(__name__).warning(
        "Failure capture unavailable: %s", _cap_err)

logger = logging.getLogger(__name__)

# ============================================================================
# Service Initialization Helpers
# ============================================================================

class ServiceInitializer:
    """Helper class for service initialization with timeout and retry"""

    @staticmethod
    async def initialize_service(
        name: str,
        init_func,
        timeout: int = 30,
        retry_count: int = 3,
        service_type: str = "class"
    ) -> Any:
        """
        Initialize a service with timeout and retry logic

        Args:
            name: Service name for logging
            init_func: Async function to initialize service
            timeout: Timeout in seconds
            retry_count: Number of retry attempts
            service_type: Type of service (class, factory, etc.)

        Returns:
            Initialized service instance or None on failure
        """
        logger.info(f"Starting {name} (type: {service_type})")

        for attempt in range(retry_count):
            try:
                # Execute initialization with timeout
                service = await asyncio.wait_for(
                    init_func(),
                    timeout=timeout
                )

                logger.info(f"  ✓ {name} initialized successfully")
                return service

            except asyncio.TimeoutError:
                logger.error(
                    f"  ✗ {name} initialization timeout "
                    f"(attempt {attempt + 1}/{retry_count})"
                )
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

            except Exception as e:
                logger.error(
                    f"  ✗ Error starting {name}: {e}",
                    exc_info=True if attempt == retry_count - 1 else False
                )
                if attempt < retry_count - 1:
                    await asyncio.sleep(2 ** attempt)

        return None


# ============================================================================
# Main TorinAI System Class
# ============================================================================

class TorinAISystem:
    """
    TorinAI Main System Orchestrator

    Manages initialization, coordination, and shutdown of all subsystems:
    - UnifiedLLMService (the teacher model) - initialized FIRST
    - Database systems (PostgreSQL, unified DB)
    - Memory and knowledge management
    - Domain reasoning and integration
    - Learning and self-improvement
    - Research and predictive intelligence
    - Health monitoring and recovery
    - Quantum computing subsystems
    - Autonomous Coordinator (THE SINGLETON)
    - Security and safety frameworks
    - Agent coordination
    - Chat servers and storage
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # System state
        self.running = False
        self.initialized = False

        # PHASE 1: THE TEACHER MODEL (initialized FIRST)
        self.llm_service = None  # UnifiedLLMService - the teacher model

        # PHASE 2: Database Systems
        self.unified_database = None  # PostgreSQL unified database
        self.db_pool = None  # Database connection pool

        # PHASE 3: Memory System
        self.memory_system = None

        # PHASE 4: Domain Systems
        self.domain_registry = None
        self.universal_ontology = None
        self.cross_domain_reasoner = None
        self.universal_domain_master = None

        # PHASE 5: Learning System
        self.learning_system = None

        # PHASE 6: Research & Intelligence
        self.research_agent = None
        self.agent_coordinator = None
        self.predictive_intelligence = None

        # PHASE 7: Health & Monitoring
        self.health_monitor = None
        self.recovery_manager = None
        self.system_watchdog = None
        self.monitoring_coordinator = None

        # PHASE 8: Quantum Computing
        self.quantum_system = None
        self.quantum_learning_bridge = None
        self.quantum_safety = None

        # PHASE 9: Autonomous Coordinator (THE SINGLETON)
        self.autonomous_coordinator = None

        # PHASE 10: Database Management
        self.database_manager = None

        # PHASE 11: Security & Safety
        self.security_system = None
        self.asi_safety = None
        self.self_improvement_engine = None
        self.integrated_security = None

        # PHASE 12: Additional Services
        self.cloud_storage_agent = None
        # Delegates to unified_llm by default; loads no model of its own.
        self.lightweight_llm_service = None  # context compression front-end

        # Additional core systems
        self.quantum_reasoning = None
        self.proof_engine = None
        self.memory_injector = None
        self.slack_notifier = None
        self.logical_integration = None
        self.audit_worker = None
        self.training_pipeline = None
        self.backup_scheduler = None
        self.testing_tools = None

        # Governance & Task Management
        self.governance_system = None  # UnifiedGovernanceTriggerSystem
        self.tool_registry = None  # Central tool registry
        self.extrinsic_task_manager = None  # External task manager

        # Statistics
        self.stats = {
            'start_time': None,
            'total_requests': 0,
            'successful_operations': 0,
            'failed_operations': 0,
            'uptime_seconds': 0,
            'services_initialized': 0,
            'services_failed': 0,
            'initialized_services': [],  # Track which services initialized
            'failed_services': []  # Track which services failed
        }

        # Service initializer
        self.service_init = ServiceInitializer()

        logger.info("TorinAI System initializing...")

    async def initialize(self):
        """Initialize all subsystems in proper dependency order"""
        if self.initialized:
            logger.warning("System already initialized")
            return

        logger.info("=" * 80)
        logger.info("TorinAI System Initialization - PRODUCTION MODE")
        logger.info("=" * 80)
        logger.info("Initialization Order:")
        logger.info("  1.  UnifiedLLMService (the teacher model) - CRITICAL FIRST")
        logger.info("  1b. Context compression service - CRITICAL")
        logger.info("  2.  Database Systems")
        logger.info("  3.  Memory System")
        logger.info("  4.  Domain Systems")
        logger.info("  5.  Learning System")
        logger.info("  6.  Research & Intelligence")
        logger.info("  7.  Health & Monitoring")
        logger.info("  8.  Quantum Computing (IBM hardware - DISABLED)")
        logger.info("  9.  Reasoning Systems")
        logger.info("  10. Autonomous Coordinator (THE SINGLETON)")
        logger.info("  11. Security, Safety, Governance & Tools")
        logger.info("  12. Additional Services (Backup, Testing)")
        logger.info("=" * 80)

        try:
            # ================================================================
            # PHASE 1: INITIALIZE THE TEACHER MODEL (CRITICAL - MUST BE FIRST)
            # ================================================================
            logger.info("")
            logger.info("PHASE 1: Initializing the teacher model (UnifiedLLMService)")
            logger.info("-" * 80)

            await self._initialize_llm_service()

            if not self.llm_service:
                logger.error(
                    "CRITICAL FAILURE: the teacher model failed to initialize!\n"
                    "Cannot proceed without LLM service. All other systems depend on it."
                )
                try:
                    from core.utils.notification_publisher import send_system_notification
                    await send_system_notification(
                        title="🚨 CRITICAL: TorinAI Core Model Failed to Initialize",
                        message="**Unified model service initialization failed!**\n\nSystem cannot start without the core model. All other systems depend on it.\n\n**Action Required:** Check model service configuration and logs.",
                        severity="critical"
                    )
                except:
                    pass
                return

            # ================================================================
            # PHASE 1b: INITIALIZE THE CONTEXT COMPRESSION SERVICE
            # Must be initialized immediately after the teacher model — required for
            # context compression, security screening, and sensitivity
            # classification throughout the rest of startup.
            # ================================================================
            logger.info("")
            logger.info("PHASE 1b: Initializing context compression service")
            logger.info("-" * 80)

            await self._initialize_lightweight_llm()

            if not self.lightweight_llm_service:
                logger.error(
                    "CRITICAL FAILURE: context compression service failed to initialize!\n"
                    "Context compression and fast screening will be unavailable."
                )
                try:
                    from core.utils.notification_publisher import send_system_notification
                    await send_system_notification(
                        title="🚨 CRITICAL: Context compression service failed",
                        message="**Context compression service failed to initialize.**\n\nSystem will run degraded.\n\n**Action Required:** check the unified LLM endpoint; the service delegates to it and loads no model of its own unless TORIN_LIGHTWEIGHT_LLM_INPROCESS=1.",
                        severity="critical"
                    )
                except:
                    pass
                # Do not abort — system can still run without it, but log loudly

            # ================================================================
            # PHASE 2: INITIALIZE DATABASE SYSTEMS
            # ================================================================
            logger.info("")
            logger.info("PHASE 2: Initializing Database Systems")
            logger.info("-" * 80)

            await self._initialize_database_systems()

            # ================================================================
            # PHASE 3: INITIALIZE MEMORY SYSTEM
            # ================================================================
            logger.info("")
            logger.info("PHASE 3: Initializing Memory System")
            logger.info("-" * 80)

            await self._initialize_memory_system()

            # ================================================================
            # PHASE 4: INITIALIZE DOMAIN SYSTEMS
            # ================================================================
            logger.info("")
            logger.info("PHASE 4: Initializing Domain Systems")
            logger.info("-" * 80)

            await self._initialize_domain_systems()

            # ================================================================
            # PHASE 5: INITIALIZE LEARNING SYSTEM
            # ================================================================
            logger.info("")
            logger.info("PHASE 5: Initializing Learning System")
            logger.info("-" * 80)

            await self._initialize_learning_system()

            # ================================================================
            # PHASE 6: INITIALIZE RESEARCH & INTELLIGENCE
            # ================================================================
            logger.info("")
            logger.info("PHASE 6: Initializing Research & Intelligence")
            logger.info("-" * 80)

            await self._initialize_research_intelligence()

            # ================================================================
            # PHASE 7: INITIALIZE HEALTH & MONITORING
            # ================================================================
            logger.info("")
            logger.info("PHASE 7: Initializing Health & Monitoring")
            logger.info("-" * 80)

            await self._initialize_health_monitoring()

            # ================================================================
            # PHASE 8: INITIALIZE QUANTUM COMPUTING - TEMPORARILY DISABLED
            # ================================================================
            # logger.info("")
            # logger.info("PHASE 8: Initializing Quantum Computing")
            # logger.info("-" * 80)

            # await self._initialize_quantum_systems()

            # ================================================================
            # PHASE 9: INITIALIZE REASONING SYSTEMS
            # ================================================================
            logger.info("")
            logger.info("PHASE 9: Initializing Reasoning Systems")
            logger.info("-" * 80)

            await self._initialize_reasoning_systems()

            # ================================================================
            # PHASE 10: INITIALIZE AUTONOMOUS COORDINATOR (THE SINGLETON)
            # ================================================================
            logger.info("")
            logger.info("PHASE 10: Initializing Autonomous Coordinator (THE SINGLETON)")
            logger.info("-" * 80)

            await self._initialize_autonomous_coordinator()

            # ================================================================
            # PHASE 11: INITIALIZE SECURITY & SAFETY
            # ================================================================
            logger.info("")
            logger.info("PHASE 11: Initializing Security & Safety")
            logger.info("-" * 80)

            await self._initialize_security_safety()

            # ================================================================
            # PHASE 12: INITIALIZE ADDITIONAL SERVICES
            # ================================================================
            logger.info("")
            logger.info("PHASE 12: Initializing Additional Services")
            logger.info("-" * 80)

            await self._initialize_additional_services()

            # ================================================================
            # FINALIZE INITIALIZATION
            # ================================================================
            self.initialized = True
            self.stats['start_time'] = datetime.now()

            logger.info("")
            logger.info("=" * 80)
            logger.info("✓ TorinAI System Initialization Complete")
            logger.info("=" * 80)
            logger.info(f"Services Initialized: {self.stats['services_initialized']}")
            logger.info(f"Services Failed: {self.stats['services_failed']}")
            logger.info(f"Start Time: {self.stats['start_time']}")
            logger.info("=" * 80)

            if self.stats['services_failed'] > 5:
                try:
                    from core.utils.notification_publisher import send_system_notification
                    await send_system_notification(
                        title="⚠️ Multiple Service Failures Detected",
                        message=f"**{self.stats['services_failed']} services failed to initialize**\n\n**Initialized:** {self.stats['services_initialized']}\n**Failed:** {self.stats['services_failed']}\n\n**Action Required:** Review logs for initialization errors.",
                        severity="warning"
                    )
                except:
                    pass

            # Send startup notification using notification_publisher
            try:
                from core.utils.notification_publisher import send_system_notification
                import os

                # Build categorized list of initialized services
                core_services = []
                intelligence_services = []
                autonomous_services = []
                support_services = []

                # Core systems (essential infrastructure)
                if getattr(self, 'llm_service', None): core_services.append("UnifiedLLM")
                if getattr(self, 'unified_database', None): core_services.append("PostgreSQL")
                if getattr(self, 'memory_system', None): core_services.append("Memory")

                # Intelligence systems
                if getattr(self, 'learning_system', None): intelligence_services.append("Learning")
                if getattr(self, 'predictive_intelligence', None): intelligence_services.append("Predictive")
                if getattr(self, 'quantum_reasoning', None): intelligence_services.append("Quantum Reasoning")
                if getattr(self, 'cross_domain_reasoner', None): intelligence_services.append("Cross-Domain")
                if getattr(self, 'research_agent', None): intelligence_services.append("Research")

                # Autonomous operations
                if getattr(self, 'autonomous_coordinator', None): autonomous_services.append("Coordinator")
                if getattr(self, 'governance_system', None): autonomous_services.append("Governance")
                if getattr(self, 'health_monitor', None): autonomous_services.append("Health Monitor")
                if getattr(self, 'recovery_manager', None): autonomous_services.append("Recovery")

                # Support systems
                if getattr(self, 'slack_notifier', None): support_services.append("Slack")
                if getattr(self, 'tool_registry', None): support_services.append("Tools")
                if getattr(self, 'backup_scheduler', None): support_services.append("Backup")

                # Build detailed message
                total_services = self.stats['services_initialized'] + self.stats['services_failed']
                success_rate = (self.stats['services_initialized'] / total_services * 100) if total_services > 0 else 100

                message_parts = [
                    f"*Status:* {self.stats['services_initialized']}/{total_services} services initialized ({success_rate:.0f}%)",
                ]

                if self.stats['services_failed'] > 0:
                    message_parts.append(f"*Failed:* {self.stats['services_failed']} services")

                # Add categorized services (compact format)
                if core_services:
                    message_parts.append(f"*Core:* {', '.join(core_services)}")
                if intelligence_services:
                    message_parts.append(f"*Intelligence:* {', '.join(intelligence_services)}")
                if autonomous_services:
                    message_parts.append(f"*Autonomous:* {', '.join(autonomous_services)}")
                if support_services:
                    message_parts.append(f"*Support:* {', '.join(support_services)}")

                # Add environment info (without sensitive data)
                env_mode = os.getenv('TORIN_MODE', 'production')
                message_parts.append(f"*Environment:* {env_mode.title()}")

                await send_system_notification(
                    title="TorinAI System Online",
                    message="\n".join(message_parts),
                    severity="info",
                    metadata={
                        "services_initialized": self.stats['services_initialized'],
                        "services_failed": self.stats['services_failed'],
                        "environment": env_mode
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send startup notification: {e}")

        except Exception as e:
            logger.error(f"Initialization failed: {e}", exc_info=True)
            raise

    # ========================================================================
    # PHASE 1: THE TEACHER MODEL (CRITICAL - MUST BE FIRST)
    # ========================================================================

    async def _initialize_llm_service(self):
        """Initialize UnifiedLLMService (the teacher model) - MUST BE FIRST"""
        try:
            from core.services.unified_llm import get_llm_service

            logger.info("🎓 Initializing the teacher model...")

            # Get singleton instance
            self.llm_service = get_llm_service()

            # Initialize with extended timeout (model loading can take 30-60s)
            success = await asyncio.wait_for(
                self.llm_service.initialize(),
                timeout=120.0  # 2 minute timeout for model loading
            )

            if success:
                logger.info("✅ TEACHER MODEL INITIALIZED")
                logger.info(f"   Model device: {self.llm_service.device.value if self.llm_service.device else 'unknown'}")
                logger.info(f"   Model loaded: {self.llm_service.model_loaded}")
                self.stats['services_initialized'] += 1

                # Test the teacher model with a simple generation
                try:
                    logger.info("   Testing the teacher model with a simple generation...")
                    from core.services.unified_llm import LLMRequest

                    test_request = LLMRequest(
                        prompt="Respond with: OK",
                        system_prompt="You are Torin.",
                        agent_type="test",
                        # Qwen3.6 reasons before answering: at 10 tokens the
                        # budget is spent on chain-of-thought and the answer is
                        # empty, so the startup self-test can never see one.
                        # Measured: 256 is the first budget that yields content.
                        max_tokens=320,
                        temperature=0.1
                    )

                    test_response = await asyncio.wait_for(
                        self.llm_service.process_request(test_request),
                        timeout=30.0
                    )

                    if test_response.success:
                        logger.info("   ✅ Teacher model test passed - ready for use")
                    else:
                        logger.warning(f"   ⚠️ Teacher model test failed: {test_response.error}")

                except Exception as e:
                    logger.warning(f"   ⚠️ Teacher model test failed: {e}")

            else:
                logger.error("❌ Teacher model failed to initialize")
                self.stats['services_failed'] += 1

        except asyncio.TimeoutError:
            logger.error("❌ Teacher model initialization timeout (exceeded 120s)")
            self.stats['services_failed'] += 1
        except Exception as e:
            logger.error(f"❌ Failed to initialize the teacher model: {e}", exc_info=True)
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 1b: CONTEXT COMPRESSION SERVICE — required before heavy context use
    # ========================================================================

    async def _initialize_lightweight_llm(self):
        """Initialize the context compression service.

        NAMED FOR WHAT IT DOES, NOT FOR A MODEL IT DOES NOT LOAD. Every line
        here announced "Qwen3-8B", but the service delegates to unified_llm --
        the process holds exactly one llama context, and inference goes to the
        Qwen3.6-35B server. Nothing opens an 8B file. Reading the startup log
        gave a model that is not running, and no mention of the one that is.
        """
        try:
            from core.services.lightweight_llm import get_lightweight_llm_service

            logger.info("⚡ Initializing context compression service...")

            async def init_lightweight():
                svc = get_lightweight_llm_service()
                success = await svc.initialize()
                return svc if success else None

            self.lightweight_llm_service = await self.service_init.initialize_service(
                "lightweight_llm_service",
                init_lightweight,
                timeout=60,  # Model loads in ~5s on MPS, generous margin
            )

            if self.lightweight_llm_service:
                logger.info("✅ Context compression active")
                self.stats['services_initialized'] += 1
            else:
                logger.error("❌ Context compression service failed — compression unavailable")
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"❌ Context compression service initialization failed: {e}", exc_info=True)
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 2: DATABASE SYSTEMS
    # ========================================================================

    async def _initialize_database_systems(self):
        """Initialize database systems"""
        # Initialize unified PostgreSQL database
        try:
            from core.database import TorinUnifiedDatabase

            logger.info("Initializing PostgreSQL unified database...")
            self.unified_database = TorinUnifiedDatabase()

            success = await asyncio.wait_for(
                self.unified_database.initialize(),
                timeout=30.0
            )

            if success:
                logger.info("✅ PostgreSQL unified database initialized")
                self.stats['services_initialized'] += 1

                # HYDRATE EPISTEMIC STATE NOW, per load_from_db's own contract:
                # "Call once after unified_db is initialized, before the agent
                # loop starts."  Nothing did.
                #
                # It was reached only lazily, from the executor and the memory
                # agent, so beliefs existed in memory only after something
                # happened to run first. The exploration loop does not wait for
                # that: get_top_exploration_targets reads
                # epistemic_engine.get_unstable_regions(), which reads the
                # in-memory belief graph, so on a fresh process it returned []
                # while 11 beliefs -- 2 of them above the entropy 0.7
                # exploration threshold -- sat unread in unified.beliefs.
                #
                # Empty is indistinguishable from "nothing worth exploring", so
                # the curiosity goal lane silently produced nothing at all.
                try:
                    from core.reasoning.epistemic_engine import get_epistemic_engine
                    uncertainty = get_epistemic_engine()._uncertainty()
                    await uncertainty.load_from_db()
                    loaded = len(getattr(uncertainty, "beliefs", {}) or {})
                    logger.info("✅ Epistemic state hydrated: %d belief(s)", loaded)
                except Exception as belief_err:
                    # Report it; an empty belief graph is a degraded state, not
                    # a reason to abort startup.
                    logger.error("❌ Belief hydration failed — exploration targets "
                                 "will be unavailable: %s", belief_err)
            else:
                logger.error("❌ PostgreSQL database initialization failed")
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"❌ Database initialization error: {e}")
            self.stats['services_failed'] += 1

        # Initialize PostgreSQL logging database
        try:
            from core.database.logging_database import get_logging_db

            logger.info("Initializing PostgreSQL logging database...")
            logging_db = get_logging_db()

            await asyncio.wait_for(
                logging_db.initialize(),
                timeout=30.0
            )

            logger.info("✅ PostgreSQL logging initialized with queue-based worker")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.warning(f"⚠️ Logging database initialization failed: {e}")

    # ========================================================================
    # PHASE 3: MEMORY SYSTEM
    # ========================================================================

    async def _initialize_memory_system(self):
        """Initialize memory system"""
        async def init_memory():
            # Import will trigger R2 client initialization
            from core.memory import get_memory_system
            memory = await get_memory_system()
            await memory.initialize()
            return memory

        self.memory_system = await self.service_init.initialize_service(
            "memory_system",
            init_memory,
            timeout=30
        )

        if self.memory_system:
            self.stats['services_initialized'] += 1
        else:
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 4: DOMAIN SYSTEMS
    # ========================================================================

    async def _initialize_domain_systems(self):
        """Initialize domain systems"""
        # Domain Registry
        try:
            from core.domain.domain_registry import get_domain_registry

            async def init_registry():
                registry = get_domain_registry()
                # Registry auto-initializes on import
                return registry

            self.domain_registry = await self.service_init.initialize_service(
                "domain_registry",
                init_registry,
                timeout=10
            )

            if self.domain_registry:
                self.stats['services_initialized'] += 1
            else:
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Domain registry initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Universal Ontology
        try:
            from core.domain.universal_ontology import get_universal_ontology

            async def init_ontology():
                ontology = get_universal_ontology()
                return ontology

            self.universal_ontology = await self.service_init.initialize_service(
                "universal_ontology",
                init_ontology,
                timeout=10
            )

            if self.universal_ontology:
                logger.info("Universal ontology initialized")
                self.stats['services_initialized'] += 1
            else:
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Universal ontology initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Cross-Domain Reasoner
        try:
            from core.domain.cross_domain_reasoner import get_cross_domain_reasoner

            async def init_reasoner():
                reasoner = get_cross_domain_reasoner()
                # Inject dependencies
                if self.domain_registry:
                    reasoner.domain_registry = self.domain_registry
                return reasoner

            self.cross_domain_reasoner = await self.service_init.initialize_service(
                "cross_domain_reasoner",
                init_reasoner,
                timeout=10
            )

            if self.cross_domain_reasoner:
                logger.info("Cross-domain reasoner initialized")
                self.stats['services_initialized'] += 1
            else:
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Cross-domain reasoner initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Universal Domain Master
        try:
            from core.integration.universal_domain_master import get_domain_master

            async def init_domain_master():
                master = get_domain_master()
                await master.initialize()
                return master

            self.universal_domain_master = await self.service_init.initialize_service(
                "universal_domain_master",
                init_domain_master,
                timeout=15
            )

            if self.universal_domain_master:
                logger.info("Universal Domain Master initialized successfully")
                self.stats['services_initialized'] += 1
            else:
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Universal domain master initialization failed: {e}")
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 5: LEARNING SYSTEM
    # ========================================================================

    async def _initialize_learning_system(self):
        """Initialize complete learning system with dependency injection"""
        try:
            from core.learning.learning_authority import get_learning_authority
            from core.learning.unified_learning_system import get_unified_learning_system
            from core.learning.enhanced_asi_self_improvement import get_asi_self_improvement
            from core.learning.improvement_monitor import get_improvement_monitor

            logger.info("=" * 80)
            logger.info("🧠 Initializing Complete Learning System")
            logger.info("=" * 80)

            async def init_learning():
                # 0. THE AUTHORITY. The substrate owns learning -- it is
                #    what EDU-01 through EDU-11 measured. It had no owner here
                #    at all: this function wired the model-based system and
                #    never mentioned induction, the rule store, active teaching
                #    or version-space learning. Anything else that learns is a
                #    CONTRIBUTOR to this, and contributes proposals rather than
                #    knowledge.
                logger.info("🧭 Establishing learning authority (substrate)...")
                authority = get_learning_authority()
                await authority.store.ensure_schema()
                self.learning_authority = authority
                logger.info("   ✅ Learning authority ready")

                # 1. Initialize UnifiedLearningSystem -- a contributor to the above.
                logger.info("📚 Initializing Unified Learning System (contributor)...")
                learning = get_unified_learning_system()
                authority.register_contributor(
                    "unified_learning_system",
                    "model-based proposer; may propose, may not attest")

                # Inject dependencies into UnifiedLearningSystem
                if self.llm_service:
                    learning.llm_service = self.llm_service
                    logger.info("   ✅ Teacher model injected")

                if self.memory_system:
                    learning.memory_system = self.memory_system
                    logger.info("   ✅ Memory system injected")

                await learning.initialize()
                logger.info("   ✅ Unified Learning System ready")

                # 2. Initialize ImprovementMonitor
                logger.info("📊 Initializing Improvement Monitor...")
                improvement_monitor = get_improvement_monitor()

                if hasattr(improvement_monitor, 'initialize'):
                    await improvement_monitor.initialize()
                logger.info("   ✅ Improvement Monitor ready")

                # 3. Initialize EnhancedASI Self-Improvement
                logger.info("🔧 Initializing Enhanced ASI Self-Improvement...")
                asi = get_asi_self_improvement()

                # Inject dependencies into EnhancedASI
                if self.llm_service:
                    asi.llm = self.llm_service
                    logger.info("   ✅ Teacher model injected")

                if self.memory_system:
                    asi.memory = self.memory_system
                    logger.info("   ✅ Memory system injected")

                # Wire improvement_monitor to ASI
                asi._monitor = improvement_monitor
                logger.info("   ✅ Improvement Monitor wired")

                if hasattr(asi, 'initialize'):
                    await asi.initialize()
                logger.info("   ✅ Enhanced ASI Self-Improvement ready")

                # Store references for later use
                learning._asi_self_improvement = asi
                learning._improvement_monitor = improvement_monitor

                logger.info("=" * 80)
                logger.info("✅ Complete Learning System Initialized")
                logger.info("   • Unified Learning System: ✓")
                logger.info("   • Improvement Monitor: ✓")
                logger.info("   • Enhanced ASI: ✓")
                logger.info("   • Dependencies Injected: ✓")
                logger.info("=" * 80)

                return (learning, asi, improvement_monitor)

            result = await self.service_init.initialize_service(
                "learning_system",
                init_learning,
                timeout=60  # Extended timeout for model loading
            )

            if result:
                self.learning_system, self.asi_self_improvement, self.improvement_monitor = result
                self.stats['services_initialized'] += 1
            else:
                self.learning_system = None
                self.asi_self_improvement = None
                self.improvement_monitor = None
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Learning system initialization failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 6: RESEARCH & INTELLIGENCE
    # ========================================================================

    async def _initialize_research_intelligence(self):
        """Initialize the agent coordinator and predictive intelligence"""
        # ── AGENT COORDINATOR (the router) ────────────────────────────────
        # This phase used to construct a bare ResearchAgent and hold it on
        # self.research_agent. That reference went nowhere: it was never passed
        # to the AutonomousCoordinator (whose self.research_agent therefore read
        # None from config), and the coordinator never used the slot anyway --
        # zero references. The one agent the system built performed no work and
        # was counted only by a status line.
        #
        # Two competing designs existed: a flat model (agents as loose top-level
        # services, no routing) and a router model (AgentCoordinator owning
        # registration, routing and lifecycle). The flat one ran and was a dead
        # end; the router one was complete and unreachable. This adopts the
        # router, which is also what the delegate_task tool routes through.
        try:
            from core.agents.agents import get_agent_coordinator

            logger.info("🤖 Initializing Agent Coordinator (research/logical/memory)...")

            async def init_agent_coordinator():
                coordinator = await get_agent_coordinator(
                    enable_monitoring=False, enable_safety=True
                )
                # Inject the teacher model into every agent that can use it.
                if self.llm_service:
                    for agent in coordinator.agents.values():
                        if hasattr(agent, "llm_service"):
                            agent.llm_service = self.llm_service
                    logger.info("   🎓 Teacher model injected into agents")
                return coordinator

            self.agent_coordinator = await self.service_init.initialize_service(
                "agent_coordinator",
                init_agent_coordinator,
                timeout=60
            )

            if self.agent_coordinator:
                agents = list(self.agent_coordinator.agents.keys())
                logger.info(
                    f"✅ Agent Coordinator ready — {len(agents)} agents: "
                    f"{[a.split('_')[0] for a in agents]}"
                )
                # Keep the legacy attribute pointing at a REAL agent so any
                # existing reader gets something that works.
                self.research_agent = next(
                    (a for aid, a in self.agent_coordinator.agents.items()
                     if aid.startswith("research")), None
                )
                self.stats['services_initialized'] += 1
            else:
                logger.error("Agent Coordinator failed to initialize — delegation unavailable")
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Agent coordinator initialization failed: {e}", exc_info=True)
            self.stats['services_failed'] += 1

        # Predictive Intelligence
        try:
            from core.intelligence.predictive_intelligence_system import get_predictive_intelligence

            async def init_predictive():
                predictive = get_predictive_intelligence()
                await predictive.initialize()
                return predictive

            self.predictive_intelligence = await self.service_init.initialize_service(
                "predictive_intelligence",
                init_predictive,
                timeout=15
            )

            if self.predictive_intelligence:
                logger.info("Predictive Intelligence System initialized")
                self.stats['services_initialized'] += 1
            else:
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Predictive intelligence initialization failed: {e}")
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 7: HEALTH & MONITORING
    # ========================================================================

    async def _initialize_health_monitoring(self):
        """Initialize health monitoring and recovery"""
        # Health Monitor
        try:
            from core.health.health_monitor import get_health_monitor

            logger.info("🏥 Initializing Health Monitor...")

            async def init_health():
                health = get_health_monitor()
                # THIS PROCESS IS THE SUBSTRATE LAYER. It grades its own internal
                # subsystems (cognition, request-validation security, safety,
                # governance); the always-on guardian grades active defense and
                # infrastructure. One owner per component, no process reporting
                # on a subsystem it does not host.
                health.set_scope("substrate")
                await health.initialize()
                return health

            self.health_monitor = await self.service_init.initialize_service(
                "health_monitor",
                init_health,
                timeout=15
            )

            if self.health_monitor:
                logger.info("✅ Health Monitor initialized successfully")
                self.stats['services_initialized'] += 1
            else:
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Health monitor initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Recovery Manager
        try:
            from core.health.recovery_manager import get_recovery_manager

            async def init_recovery():
                recovery = get_recovery_manager()
                return recovery

            self.recovery_manager = await self.service_init.initialize_service(
                "recovery_manager",
                init_recovery,
                timeout=10
            )

            if self.recovery_manager:
                self.stats['services_initialized'] += 1
            else:
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Recovery manager initialization failed: {e}")
            self.stats['services_failed'] += 1

        # System Watchdog
        #
        # Nothing in this file referenced the watchdog, so it was never
        # constructed and never started: the component that detects failing
        # subsystems and drives recovery was absent for the whole run, and the
        # health system reported CRITICAL on watchdog_running for exactly that
        # reason. Its start() also starts the health monitor's own periodic
        # loop, which was likewise never running -- so health was only ever
        # measured when something asked for it directly.
        #
        # Constructed here and started in start(), matching the audit worker and
        # backup scheduler: initialize() builds, start() runs the loops.
        try:
            from core.health.system_watchdog import get_system_watchdog

            async def init_watchdog():
                return get_system_watchdog()

            self.system_watchdog = await self.service_init.initialize_service(
                "system_watchdog",
                init_watchdog,
                timeout=10
            )

            if self.system_watchdog:
                self.stats['services_initialized'] += 1
            else:
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"System watchdog initialization failed: {e}")
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 8: QUANTUM COMPUTING
    # ========================================================================

    async def _initialize_quantum_systems(self):
        """Initialize quantum computing systems"""
        # Quantum System
        try:
            from core.quantum.quantum_factory import initialize_quantum_computing

            logger.info("🚀 Initializing Torin Quantum Computing Subsystem with REAL QUANTUM HARDWARE")
            logger.info("  Calling factory function: initialize_quantum_computing()")

            async def init_quantum():
                system = await initialize_quantum_computing()
                return system

            self.quantum_system = await self.service_init.initialize_service(
                "quantum_system",
                init_quantum,
                timeout=60,
                service_type="factory"
            )

            if self.quantum_system:
                self.stats['services_initialized'] += 1
            else:
                logger.warning("⚠️ IBM Quantum provider initialization failed - continuing without quantum hardware")
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Quantum system initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Quantum Learning Bridge
        try:
            from core.quantum.quantum_learning_bridge import initialize_quantum_learning_bridge

            async def init_bridge():
                # Check if LLM service is initialized
                if not self.llm_service or not self.llm_service.model_loaded:
                    logger.warning("LLM service is not initialized")
                    return None

                bridge = await initialize_quantum_learning_bridge()
                return bridge

            self.quantum_learning_bridge = await self.service_init.initialize_service(
                "quantum_learning_bridge",
                init_bridge,
                timeout=60,
                service_type="factory"
            )

            if self.quantum_learning_bridge:
                self.stats['services_initialized'] += 1
            else:
                logger.warning("Failed to initialize quantum learning bridge: LLM service is not initialized")
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Quantum learning bridge initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Quantum Safety
        try:
            from core.quantum.quantum_safety import initialize_quantum_safety

            async def init_safety():
                safety = await initialize_quantum_safety()
                return safety

            self.quantum_safety = await self.service_init.initialize_service(
                "quantum_safety",
                init_safety,
                timeout=60,
                service_type="factory"
            )

            if self.quantum_safety:
                self.stats['services_initialized'] += 1
            else:
                logger.warning("Hybrid quantum processor initialization failed")
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Quantum safety initialization failed: {e}")
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 9: REASONING SYSTEMS
    # ========================================================================

    async def _initialize_reasoning_systems(self):
        """Initialize reasoning systems"""
        # Quantum Reasoning System
        try:
            from core.reasoning.unified_quantum_reasoning_system import get_quantum_reasoning_system

            logger.info("Initializing quantum reasoning system...")
            self.quantum_reasoning = get_quantum_reasoning_system()
            logger.info("✓ Quantum reasoning system initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Quantum reasoning initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Proof Engine
        try:
            from core.reasoning.advanced_proof_engine import get_proof_engine

            logger.info("Initializing proof engine...")
            self.proof_engine = get_proof_engine()
            logger.info("✓ Proof engine initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Proof engine initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Memory Injector
        try:
            from core.memory.utils.memory_injector import get_memory_injector

            logger.info("Initializing memory injector...")
            self.memory_injector = get_memory_injector()
            logger.info("✓ Memory injector initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Memory injector initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Logical Integration
        try:
            from core.agents.logical.logical_integration import get_logical_integration

            logger.info("Initializing logical integration...")
            self.logical_integration = get_logical_integration()

            # Connect proof engine to logical integration
            if self.proof_engine:
                self.logical_integration.proof_engine = self.proof_engine

            logger.info("✓ Logical integration initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Logical integration initialization failed: {e}")
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 10: AUTONOMOUS COORDINATOR (THE SINGLETON)
    # ========================================================================

    async def _initialize_autonomous_coordinator(self):
        """Initialize Autonomous Coordinator (THE SINGLETON)"""
        try:
            from core.agents.autonomous.autonomous_coordinator import get_autonomous_coordinator

            logger.info("Initializing Autonomous Coordinator (THE SINGLETON)...")

            async def init_coordinator():
                coordinator = await get_autonomous_coordinator(teacher_model=self.llm_service)

                # Inject dependencies
                if self.quantum_reasoning:
                    coordinator.quantum_reasoning = self.quantum_reasoning
                if self.proof_engine:
                    coordinator.proof_engine = self.proof_engine

                # Inject learning systems (SINGLETON pattern - only ONE instance)
                if self.learning_system:
                    coordinator.unified_learning = self.learning_system
                    logger.info("✓ Unified Learning System injected into coordinator")

                if hasattr(self, 'asi_self_improvement') and self.asi_self_improvement:
                    coordinator.asi_self_improvement = self.asi_self_improvement
                # Inject the INITIALIZED singleton. The coordinator otherwise
                # constructs its own PredictiveIntelligenceSystem that main never
                # initialize()s — two live instances of one subsystem, with the
                # config slot meant to receive this one left permanently None.
                if getattr(self, 'predictive_intelligence', None):
                    coordinator.intelligence = self.predictive_intelligence
                    logger.info("✓ Autonomous coordinator connected to predictive intelligence")
                    logger.info("✓ ASI Self-Improvement injected into coordinator")

                # Inject governance system (SINGLETON pattern - only ONE instance)
                if hasattr(self, 'governance_system') and self.governance_system:
                    coordinator.governance = self.governance_system
                    logger.info("✓ Governance System injected into coordinator")

                # Inject health monitoring systems (SINGLETON pattern - only ONE instance)
                if hasattr(self, 'health_monitor') and self.health_monitor:
                    coordinator.health_monitor = self.health_monitor
                    logger.info("✓ Health Monitor injected into coordinator")

                if hasattr(self, 'recovery_manager') and self.recovery_manager:
                    coordinator.recovery_manager = self.recovery_manager
                    logger.info("✓ Recovery Manager injected into coordinator")

                # The agent router. Previously the autonomous coordinator read
                # self.research_agent from config, which main.py never passed --
                # so it was always None, and unused even so.
                if getattr(self, 'agent_coordinator', None):
                    coordinator.agent_coordinator = self.agent_coordinator
                    coordinator.research_agent = self.research_agent
                    logger.info("✓ Agent Coordinator injected into coordinator")

                await coordinator.initialize()
                return coordinator

            self.autonomous_coordinator = await self.service_init.initialize_service(
                "autonomous_controller",
                init_coordinator,
                timeout=30
            )

            if self.autonomous_coordinator:
                # Wire up the CANONICAL memory injector. main.py constructs it
                # (line ~1178); without this the coordinator would fetch its own
                # via get_memory_injector(), giving two owners of one mechanism.
                # One injector, injected — not two, discovered independently.
                if getattr(self, 'memory_injector', None):
                    self.autonomous_coordinator.memory_injector = self.memory_injector
                    logger.info("✓ Autonomous coordinator connected to memory injector")

                # Adaptive tool learning — ONE owner, ONE persistence authority.
                #
                # The executor used to build its own reader and its own writer,
                # each resolving a database independently. The reader recovered
                # through an internal fallback; the writer sat behind
                # `if self.db_manager:` — an attribute the executor never
                # assigns — so tool_usage_history stayed empty and every task
                # logged "No historical data yet", indistinguishable from a
                # genuine cold start, for the life of the system.
                #
                # Constructed here from the canonical database and injected, so
                # read and write are symmetric by construction rather than by
                # two constructors happening to pick the same DB.
                try:
                    from core.learning.adaptive_tool_owner import get_adaptive_tool_learning
                    from core.database import get_database_manager

                    _atl = get_adaptive_tool_learning(get_database_manager())
                    self.autonomous_coordinator.adaptive_tool_learning = _atl
                    if getattr(self.autonomous_coordinator, "executor", None):
                        self.autonomous_coordinator.executor.adaptive_tool_learning = _atl
                        # The attribute both halves were gating on. Present now,
                        # so the writer is reachable.
                        self.autonomous_coordinator.executor.db_manager = get_database_manager()
                    _st = await _atl.status()
                    logger.info(
                        f"✓ Adaptive tool learning connected — mode={_st['mode']} "
                        f"rows={_st['history_rows']} measured={_st['measured_affinities']}"
                    )
                except Exception as e:
                    logger.error(f"Adaptive tool learning NOT connected: {e}", exc_info=True)

                # Universal Domain Master — the Postgres-backed authority for
                # what domains exist and for cross-domain reasoning.
                #
                # It is initialized above (Phase 4, _initialize_domain_systems)
                # and was never handed to anyone. The coordinator reads it from
                # `self.config.get("universal_domain_master")` (coordinator:439),
                # a key main.py does not set, so self.universal_domain_master was
                # always None and perform_cross_domain_reasoning (:2601) returned
                # at its `if not self.universal_domain_master` guard on every
                # call — logging "not available" for a service that was running.
                #
                # UnifiedLearningSystem has the same hole: __init__ takes
                # domain_master=None and NOTHING in the codebase passes it, so
                # its domain-aware paths never had an authority to consult.
                if getattr(self, 'universal_domain_master', None):
                    self.autonomous_coordinator.universal_domain_master = self.universal_domain_master
                    # The registry too. coordinator:438 reads it from
                    # config["domain_registry"], a key main.py never set, so the
                    # guard at :2745 (`if self.universal_domain_master and
                    # self.domain_registry`) was permanently False and
                    # list_domains() was unreachable. main.py builds the registry
                    # at :721 and previously attached it only to the reasoner.
                    if getattr(self, 'domain_registry', None):
                        self.autonomous_coordinator.domain_registry = self.domain_registry
                    if getattr(self, 'learning_system', None) is not None:
                        self.learning_system.domain_master = self.universal_domain_master
                    try:
                        _dstats = await self.universal_domain_master.get_statistics()
                        logger.info(
                            f"✓ Universal Domain Master connected to coordinator — {_dstats}"
                        )
                    except Exception as e:
                        logger.info(
                            "✓ Universal Domain Master connected to coordinator "
                            f"(statistics unavailable: {e})"
                        )
                else:
                    logger.error(
                        "Universal Domain Master NOT connected — cross-domain "
                        "reasoning will refuse every request"
                    )

                # Wire up governance system reference
                if self.governance_system:
                    self.autonomous_coordinator.governance_system = self.governance_system
                    logger.info("✓ Autonomous coordinator connected to governance system")

                # Wire up security audit worker reference
                if self.audit_worker:
                    self.autonomous_coordinator.security_audit_worker = self.audit_worker
                    logger.info("✓ Autonomous coordinator connected to security audit worker")

                # Wire up monitoring coordinator integrations (if monitoring enabled)
                if hasattr(self.autonomous_coordinator, 'monitoring_coordinator') and self.autonomous_coordinator.monitoring_coordinator:
                    if self.slack_notifier and hasattr(self.autonomous_coordinator.monitoring_coordinator, 'set_slack_notifier'):
                        self.autonomous_coordinator.monitoring_coordinator.set_slack_notifier(self.slack_notifier)
                        logger.info("✓ Monitoring coordinator connected to Slack notifier")

                    if hasattr(self.autonomous_coordinator.monitoring_coordinator, 'set_autonomous_coordinator'):
                        self.autonomous_coordinator.monitoring_coordinator.set_autonomous_coordinator(self.autonomous_coordinator)
                        logger.info("✓ Monitoring coordinator connected to autonomous coordinator")

                logger.info("✅ Autonomous Coordinator (THE SINGLETON) initialized")
                self.stats['services_initialized'] += 1
            else:
                logger.error("Failed to initialize autonomous_controller - check logs above for details")
                self.stats['services_failed'] += 1

        except Exception as e:
            logger.error(f"Autonomous coordinator initialization failed: {e}")
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 11: SECURITY & SAFETY
    # ========================================================================

    async def _initialize_security_safety(self):
        """Initialize security and safety systems"""
        # Slack Notifier
        try:
            from core.integration.slack_notifier import get_slack_notifier

            logger.info("Initializing Slack notifier...")
            self.slack_notifier = get_slack_notifier()
            logger.info("✓ Slack notifier initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Slack notifier initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Security Audit Worker
        try:
            from core.security.security_audit_worker import get_audit_worker

            logger.info("Initializing security audit worker...")
            self.audit_worker = get_audit_worker()

            # Wire up slack integration if method exists
            if self.slack_notifier and hasattr(self.audit_worker, 'set_slack_notifier'):
                self.audit_worker.set_slack_notifier(self.slack_notifier)

            # Wire up autonomous coordinator integration for remediation tasks
            if self.autonomous_coordinator and hasattr(self.audit_worker, 'set_autonomous_coordinator'):
                self.audit_worker.set_autonomous_coordinator(self.autonomous_coordinator)
                logger.info("✓ Security audit worker connected to autonomous coordinator")

            # Wire up governance system integration
            if self.governance_system and hasattr(self.audit_worker, 'set_governance_system'):
                self.audit_worker.set_governance_system(self.governance_system)
                logger.info("✓ Security audit worker connected to governance system")

            # Wire up safety framework integration.
            #
            # This used to pass `self.asi_safety`, which is assigned None at
            # construction and NEVER assigned anything else -- so the condition
            # was always false and the audit worker was never connected to
            # anything. It now receives the actual authority for action safety.
            #
            # Stated plainly because it is still true: the audit worker STORES
            # this and no code path reads it yet. The hook is connected to the
            # right object rather than to None, and the log says what happened
            # rather than implying an integration that does not exist.
            if hasattr(self.audit_worker, 'set_safety_framework'):
                from core.security.safety_framework import get_safety_framework
                self.audit_worker.set_safety_framework(get_safety_framework())
                logger.info("✓ Security audit worker holds a safety framework reference "
                            "(no consumer reads it yet)")

            # Wire up integrated security system (active defense)
            if self.integrated_security and hasattr(self.audit_worker, 'set_integrated_security'):
                self.audit_worker.set_integrated_security(self.integrated_security)

            logger.info("✓ Security audit worker initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Security audit worker initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Security Training Pipeline
        try:
            from core.security.security_training_pipeline import get_training_pipeline

            logger.info("Initializing security training pipeline...")
            self.training_pipeline = get_training_pipeline()

            # Wire up slack integration
            if self.slack_notifier:
                self.training_pipeline.set_slack_notifier(self.slack_notifier)

            logger.info("✓ Security training pipeline initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Security training pipeline initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Integrated Security System (Active Defense)
        try:
            from core.security import create_integrated_security_system
            import os

            logger.info("Initializing integrated security system (active defense)...")

            # Get API keys from environment
            abuseipdb_key = os.getenv('ABUSEIPDB_API_KEY')
            virustotal_key = os.getenv('VIRUSTOTAL_API_KEY')
            otx_key = os.getenv('OTX_API_KEY')
            cloudflare_token = os.getenv('CLOUDFLARE_API_TOKEN')
            cloudflare_zone = os.getenv('CLOUDFLARE_ZONE_ID')
            
            # Firewall mode: PRODUCTION by default - set TORIN_FIREWALL_TEST=true to disable
            # NOTE: Requires root/sudo privileges for iptables/pf rules
            firewall_test_mode = os.getenv('TORIN_FIREWALL_TEST', 'false').lower() == 'true'
            if not firewall_test_mode:
                logger.info("🔥 Firewall PRODUCTION MODE - real iptables/pf rules will be applied")
            else:
                logger.info("⚠️  Firewall TEST MODE - dry run, no actual rules applied")

            # Initialize integrated security system
            self.integrated_security = create_integrated_security_system(
                test_mode=firewall_test_mode,  # test_mode=False means production (real rules)
                cloudflare_api_token=cloudflare_token,
                cloudflare_zone_id=cloudflare_zone,
                abuseipdb_key=abuseipdb_key,
                virustotal_key=virustotal_key,
                otx_key=otx_key,
                use_singleton=True
            )

            # REPORT THE MODE THAT IS ACTUALLY IN FORCE, not the one requested.
            # The log above states the intended mode before the call; if a
            # singleton already existed the call returns it unchanged, so the
            # only truthful source is the object that came back.
            actual_test_mode = self.integrated_security.get('test_mode')
            if actual_test_mode is not None and bool(actual_test_mode) != firewall_test_mode:
                logger.error(
                    "⚠️ Firewall mode in force (test_mode=%s) differs from the mode "
                    "requested (test_mode=%s); an earlier caller created the "
                    "security system", actual_test_mode, firewall_test_mode)
            else:
                logger.info("Firewall mode in force: test_mode=%s", actual_test_mode)

            # Restore persisted threat intel state (best-effort)
            threat_intel = self.integrated_security.get('threat_intel')
            if threat_intel and hasattr(threat_intel, 'load_persisted_state'):
                try:
                    await threat_intel.load_persisted_state()
                    logger.info("✓ Threat intelligence persistence state restored")
                except Exception as e:
                    logger.warning(f"Threat intelligence persistence restore failed: {e}")

            # Start background monitoring
            threat_blocking = self.integrated_security.get('threat_blocking')
            if threat_blocking and hasattr(threat_blocking, 'start_monitoring'):
                await threat_blocking.start_monitoring()
                logger.info("✓ Threat blocking engine monitoring started")

            # Start firewall monitoring (verifies rules are still in place)
            firewall = self.integrated_security.get('firewall')
            if firewall and hasattr(firewall, 'start_monitoring'):
                # Wire health callback to monitoring coordinator
                if self.monitoring_coordinator and hasattr(self.monitoring_coordinator, 'singleton_callback'):
                    firewall.set_health_callback(self.monitoring_coordinator.singleton_callback)
                await firewall.start_monitoring()
                logger.info("✓ Firewall manager monitoring started (rule verification)")

            # Wire integrated security to SecurityAuditWorker
            if self.audit_worker and hasattr(self.audit_worker, 'set_integrated_security'):
                self.audit_worker.set_integrated_security(self.integrated_security)
                logger.info("✓ Security audit worker connected to integrated security system")

            # Wire SecurityController to AutonomousCoordinator
            security_controller = self.integrated_security.get('security_controller')
            if security_controller and self.autonomous_coordinator:
                if hasattr(security_controller, 'set_autonomous_coordinator'):
                    security_controller.set_autonomous_coordinator(self.autonomous_coordinator)
                    logger.info("✓ SecurityController connected to AutonomousCoordinator")

                # Also set SecurityController on AutonomousCoordinator (if not already set)
                if not hasattr(self.autonomous_coordinator, 'security_controller') or not self.autonomous_coordinator.security_controller:
                    self.autonomous_coordinator.security_controller = security_controller
                    logger.info("✓ AutonomousCoordinator connected to SecurityController")

            logger.info("✓ Integrated security system initialized (active defense enabled)")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Integrated security system initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Governance System (SINGLETON pattern)
        try:
            from core.governance import get_unified_governance

            logger.info("Initializing governance system (singleton)...")
            self.governance_system = get_unified_governance()  # Get singleton instance

            # Wire up slack integration
            if self.slack_notifier:
                self.governance_system.slack_notifier = self.slack_notifier

            logger.info("✓ Governance system initialized (singleton)")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Governance system initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Tool Registry
        try:
            from core.tools.tool_registry import get_tool_registry

            logger.info("Initializing tool registry...")
            self.tool_registry = get_tool_registry()

            # Wire up governance integration
            if self.governance_system:
                self.tool_registry.governance_system = self.governance_system

            # PROJECT THE TOOLS AS OPERATORS, EVERY BOOT.
            #
            # A tool is an operator the substrate can invoke, and its parameter
            # list is a precondition list in another notation. Projecting them
            # is what lets cross-domain grounding recognise a situation as
            # something there is already a tool for, rather than only as a
            # learned rule.
            #
            # This had no production caller at all -- only an experiment -- so
            # the projection reflected whatever the tool set looked like the
            # last time somebody ran it by hand. A tool added, removed or
            # re-declared since then never reached the concept graph. Running it
            # here makes the projection a fact about the tools THIS process
            # actually has.
            #
            # Idempotent: concept identity is a semantic fingerprint, so a
            # re-run reinforces the existing concepts instead of duplicating
            # them. Failure is logged and never fatal -- the registry is usable
            # whether or not the concept layer accepted the projection.
            try:
                projection = await self.tool_registry.project_capabilities()
                logger.info(
                    "✓ Tools projected as operators: %d/%d (%d declare no "
                    "structure, %d unreadable)",
                    projection.get("projected", 0), projection.get("tools", 0),
                    projection.get("no_structure", 0), projection.get("failed", 0))
            except Exception as e:
                logger.warning("Tool capability projection failed: %s: %s",
                               type(e).__name__, e)

            logger.info("✓ Tool registry initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Tool registry initialization failed: {e}")
            self.stats['services_failed'] += 1

    # ========================================================================
    # PHASE 12: ADDITIONAL SERVICES
    # ========================================================================

    async def _initialize_additional_services(self):
        """Initialize additional services"""
        # NOTE: the context compression service is initialized in Phase 1b — immediately
        # after the teacher model — because it is required for context compression throughout
        # the system. It is NOT initialized here.

        # Backup Scheduler
        try:
            from core.services.backup_scheduler import get_backup_scheduler

            logger.info("Initializing backup scheduler...")
            self.backup_scheduler = get_backup_scheduler()

            if self.slack_notifier:
                self.backup_scheduler.set_slack_notifier(self.slack_notifier)

            logger.info("✓ Backup scheduler initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Backup scheduler initialization failed: {e}")
            self.stats['services_failed'] += 1

        # Testing & Validation Tools
        try:
            from core.tools.testing_validation_tools import get_testing_tools

            logger.info("Initializing testing tools...")
            self.testing_tools = get_testing_tools()

            if self.slack_notifier:
                self.testing_tools.set_slack_notifier(self.slack_notifier)

            logger.info("✓ Testing tools initialized")
            self.stats['services_initialized'] += 1

        except Exception as e:
            logger.error(f"Testing tools initialization failed: {e}")
            self.stats['services_failed'] += 1

    # ========================================================================
    # SERVICE LIFECYCLE
    # ========================================================================

    async def start(self):
        """Start all services"""
        if not self.initialized:
            # The result is CHECKED. Discarding it meant a failed initialize was
            # followed by the work it was meant to enable, and the real failure
            # resurfaced later disguised as something else.
            if await self.initialize() is False:
                raise RuntimeError(
                    type(self).__name__ + ' could not initialize; refusing to '
                    'continue as though it had')

        if self.running:
            logger.warning("System already running")
            return

        logger.info("Starting TorinAI services...")

        try:
            # Start autonomous coordinator
            if self.autonomous_coordinator:
                await self.autonomous_coordinator.start_coordination()
                logger.info("✓ Autonomous coordinator started")

            # Start security monitoring
            if self.audit_worker:
                await self.audit_worker.start_monitoring()
                logger.info("✓ Security monitoring started")

            # Start system watchdog (also starts the health monitoring loop)
            if self.system_watchdog:
                await self.system_watchdog.start()
                logger.info("✓ System watchdog started")

            # Start backup scheduler ONLY if no guardian owns it. Backups are a
            # system (always-on) concern now owned by the guardian; the substrate
            # runs the scheduler only as a fallback when no guardian is present,
            # so exactly one scheduler ever runs.
            if self.backup_scheduler:
                from core.health import system_control as _sc
                guardian_owns_backup = await _sc.guardian_present(
                    getattr(self, "db_manager", None))
                if guardian_owns_backup:
                    logger.info("✓ Backup scheduler owned by the guardian; "
                                "substrate defers")
                else:
                    await self.backup_scheduler.start_scheduler()
                    logger.info("✓ Backup scheduler started (no guardian present)")

            # Set running flag
            self.running = True

            logger.info("✓ All services started successfully")
            logger.info("🎉 Service initialization complete!")
            
            # Mark health monitoring startup complete so alerts can now be generated
            if self.autonomous_coordinator and hasattr(self.autonomous_coordinator, 'monitoring_coordinator'):
                mc = self.autonomous_coordinator.monitoring_coordinator
                if mc and hasattr(mc, 'mark_startup_complete'):
                    mc.mark_startup_complete()

        except Exception as e:
            logger.error(f"Service startup failed: {e}", exc_info=True)
            raise

    async def run(self):
        """Main event loop"""
        if not self.running:
            await self.start()

        logger.info("TorinAI system running... (Press Ctrl+C to stop)")
        logger.info("📡 Creating startup signal...")
        logger.info("📡 Startup signal created - proceeding to launch servers")

        # System control loop — the guardian (core/guardian) owns monitoring/
        # security status and control when it is running; the substrate runs this
        # loop ONLY as a fallback, when no guardian is present, so a bare substrate
        # is still observable. `_guardian_present` checks a fresh heartbeat.
        self._system_control_task = asyncio.create_task(self._system_control_loop())

        try:
            heartbeat_interval = 60  # Log heartbeat every 60 seconds
            last_heartbeat = datetime.now()

            while self.running:
                # Update uptime
                if self.stats['start_time']:
                    self.stats['uptime_seconds'] = (
                        datetime.now() - self.stats['start_time']
                    ).total_seconds()

                # Log periodic heartbeat
                now = datetime.now()
                if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                    uptime_mins = int(self.stats['uptime_seconds'] / 60)
                    logger.info(f"💓 System heartbeat - Uptime: {uptime_mins}m | Services: {self.stats['services_initialized']}")
                    if self.autonomous_coordinator:
                        logger.info(f"🤖 Singleton active: {self.autonomous_coordinator.active} | "
                                  f"Cycles: {self.autonomous_coordinator.stats.get('cycles_completed', 0)}")
                    last_heartbeat = now

                # Main loop - handle events, monitoring, etc.
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)

    async def _system_control_loop(self):
        """Publish real system status and apply dashboard control commands.

        The Monitoring and Security tabs need two things that only this process
        can provide: the live status of each system (read off the objects this
        process holds) and the execution of a stop/restart the dashboard asked
        for (which only this process can perform, because it holds the objects).

        A small independent loop rather than a hook in an existing one, so a
        slow cycle elsewhere cannot delay a status refresh or a control command,
        and so it keeps working even while the coordinator is busy.
        """
        from core.health import system_control as sc

        logger.info("System control loop started (fallback; the guardian owns this when present)")
        while not getattr(self, "_shutting_down", False):
            try:
                db = self.db_manager if hasattr(self, "db_manager") else None
                # Advertise substrate liveness FIRST, before any deferral. The
                # heartbeat means "the substrate process is alive" regardless of
                # who owns control, so the health monitor can tell an
                # intentionally stopped substrate apart from a regressed
                # subsystem and stop screaming -100% at every cognitive system.
                await sc.publish_substrate_heartbeat(db)
                # Defer to a live guardian: if one is publishing, it holds the
                # real objects and this process must not fight it on the queue.
                if await sc.guardian_present(db):
                    await asyncio.sleep(2.0)
                    continue
                live = sc.resolve_live(self)
                await sc.publish_status(live, db)
                await sc.drain_commands(live, db)
            except asyncio.CancelledError:
                break
            except Exception as error:
                logger.error("system control loop error: %s", error)
            await asyncio.sleep(2.0)
        logger.info("System control loop stopped")

    async def shutdown(self):
        """Graceful shutdown"""
        # Guard against multiple shutdown calls
        if hasattr(self, '_shutdown_in_progress') and self._shutdown_in_progress:
            logger.debug("Shutdown already in progress, ignoring duplicate call")
            return

        self._shutdown_in_progress = True

        logger.info("=" * 80)
        logger.info("TorinAI System Shutdown Initiated")
        logger.info("=" * 80)

        self.running = False

        try:
            # Stop services
            logger.info("Stopping services...")

            # Shutdown autonomous coordinator first (stops coordination cycle + modules)
            if self.autonomous_coordinator:
                try:
                    await self.autonomous_coordinator.shutdown()
                    logger.info("✓ Autonomous coordinator stopped")
                except Exception as e:
                    logger.error(f"Error stopping autonomous coordinator: {e}")

            if self.audit_worker:
                await self.audit_worker.stop_monitoring()
                logger.info("✓ Security monitoring stopped")

            if self.backup_scheduler:
                await self.backup_scheduler.stop_scheduler()
                logger.info("✓ Backup scheduler stopped")

            # Shutdown Lightweight LLM (before VLM)
            if self.lightweight_llm_service:
                await self.lightweight_llm_service.shutdown()
                logger.info("✓ Context compression service stopped")

            # Shutdown the teacher model
            if self.llm_service:
                logger.info("Shutting down the teacher model...")
                await self.llm_service.shutdown()
                logger.info("✓ Teacher model shutdown complete")

            # Close logging database (coordinator's log_db)
            if self.autonomous_coordinator and hasattr(self.autonomous_coordinator, 'log_db'):
                try:
                    if self.autonomous_coordinator.log_db:
                        await self.autonomous_coordinator.log_db.close()
                        logger.info("✓ Logging database closed")
                except Exception as e:
                    logger.warning(f"Error closing logging database: {e}")

            # Close unified database connections (singleton - closes all 3 pools)
            if self.unified_database:
                await self.unified_database.close()
                logger.info("✓ Database connections closed")

            # Send shutdown notifications
            try:
                from core.utils.notification_publisher import send_system_notification
                await send_system_notification(
                    title="TorinAI System Stopped",
                    message="System shutdown completed successfully",
                    severity="info",
                    metadata=self.stats
                )
            except Exception as e:
                logger.warning(f"Failed to send shutdown notification: {e}")

            if self.slack_notifier:
                try:
                    uptime_seconds = self.stats.get('uptime_seconds', 0)
                    uptime_hours = uptime_seconds / 3600
                    uptime_str = f"{uptime_hours:.1f}h" if uptime_hours >= 1 else f"{uptime_seconds/60:.1f}m"

                    shutdown_message = {
                        "text": "🛑 *TorinAI System Shutdown*",
                        "blocks": [
                            {
                                "type": "header",
                                "text": {
                                    "type": "plain_text",
                                    "text": "🛑 System Shutdown Complete"
                                }
                            },
                            {
                                "type": "section",
                                "fields": [
                                    {"type": "mrkdwn", "text": f"*Uptime:*\n{uptime_str}"},
                                    {"type": "mrkdwn", "text": f"*Services:*\n{self.stats.get('services_initialized', 0)} active"},
                                    {"type": "mrkdwn", "text": f"*Operations:*\n{self.stats.get('successful_operations', 0)} successful"},
                                    {"type": "mrkdwn", "text": f"*Failed:*\n{self.stats.get('failed_operations', 0)} errors"}
                                ]
                            },
                            {
                                "type": "context",
                                "elements": [
                                    {
                                        "type": "mrkdwn",
                                        "text": f"Stopped at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                                    }
                                ]
                            }
                        ]
                    }
                    await self.slack_notifier._send_slack_notification(shutdown_message)
                    logger.info("✓ Shutdown notification sent to Slack")
                except Exception as e:
                    logger.warning(f"Failed to send Slack shutdown notification: {e}")

            logger.info("=" * 80)
            logger.info("✓ TorinAI System Shutdown Complete")
            logger.info("=" * 80)

        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)

    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        status = {
            'running': self.running,
            'initialized': self.initialized,
            'uptime_seconds': self.stats['uptime_seconds'],
            'start_time': self.stats['start_time'].isoformat() if self.stats['start_time'] else None,
            'services_initialized': self.stats['services_initialized'],
            'services_failed': self.stats['services_failed'],
            'subsystems': {}
        }

        # Get subsystem status
        try:
            if self.llm_service:
                status['subsystems']['llm_service'] = {
                    'loaded': self.llm_service.model_loaded,
                    'device': self.llm_service.device.value if self.llm_service.device else 'unknown',
                    'statistics': self.llm_service.get_statistics()
                }

            if self.quantum_reasoning:
                status['subsystems']['quantum_reasoning'] = await self.quantum_reasoning.get_statistics()

            if self.proof_engine:
                status['subsystems']['proof_engine'] = await self.proof_engine.get_statistics()

            if self.memory_injector:
                status['subsystems']['memory_injector'] = await self.memory_injector.get_statistics()

            if self.audit_worker:
                status['subsystems']['audit_worker'] = await self.audit_worker.get_statistics()

            if self.training_pipeline:
                status['subsystems']['training_pipeline'] = await self.training_pipeline.get_statistics()

            if self.backup_scheduler:
                status['subsystems']['backup_scheduler'] = await self.backup_scheduler.get_statistics()

            if self.testing_tools:
                status['subsystems']['testing_tools'] = await self.testing_tools.get_statistics()

        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            status['error'] = str(e)

        return status


# ============================================================================
# Global Instance
# ============================================================================

_system: Optional[TorinAISystem] = None


def get_system() -> TorinAISystem:
    """Get global system instance"""
    global _system
    if _system is None:
        _system = TorinAISystem()
    return _system


# ============================================================================
# Main Entry Point
# ============================================================================

async def main():
    """Main entry point"""
    system = get_system()

    # Setup signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        """Handle shutdown signals"""
        logger.info(f"\nReceived signal {sig}, initiating shutdown...")
        asyncio.create_task(system.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize and start system
        await system.initialize()
        await system.start()

        # Run main event loop
        await system.run()

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        # Ensure clean shutdown
        await system.shutdown()


if __name__ == "__main__":
    # Create logs and runtime directories if they don't exist
    os.makedirs("logs", exist_ok=True)
    runtime_dir = Path(__file__).parent.parent / "runtime"
    runtime_dir.mkdir(exist_ok=True)

    # Write PID file for robust process management
    pid_file = runtime_dir / "torin_main.pid"
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"PID file written: {pid_file} (PID: {os.getpid()})")
    except Exception as e:
        logger.warning(f"Failed to write PID file: {e}")

    try:
        # Run the system
        asyncio.run(main())
    finally:
        # Clean up PID file on exit
        try:
            if pid_file.exists():
                pid_file.unlink()
                logger.info(f"PID file removed: {pid_file}")
        except Exception as e:
            logger.warning(f"Failed to remove PID file: {e}")
