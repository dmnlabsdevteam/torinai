# TorinAI Singleton Architecture Graph
**Version**: 7.2
**Date**: 2026-02-05
**Status**: Production Architecture

---

## 🧠 Core Architecture: Single Brain, Multiple Interfaces

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TORIN SINGLETON ECOSYSTEM                             │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                    🧠 THE BRAIN (Singleton)                        │     │
│  │                                                                     │     │
│  │              UnifiedLLMService (VLM - Vision + Language)           │     │
│  │              Model: Qwen2.5-VL-32B-Instruct-Q8_0.gguf              │     │
│  │              Device: MPS/CUDA/CPU (Auto-detect)                    │     │
│  │              Purpose: Source of ALL intelligence                    │     │
│  │                                                                     │     │
│  │  ┌──────────────────────────────────────────────────────────────┐  │     │
│  │  │  Model Interchangeability:                                   │  │     │
│  │  │  • LOCAL_MODEL_PATH environment variable                     │  │     │
│  │  │  • config.model_path parameter                               │  │     │
│  │  │  • Any llama-cpp compatible GGUF model                       │  │     │
│  │  │  • Current: Qwen2.5-VL-32B (vision-language unified)         │  │     │
│  │  │  • Can swap to: Llama 3.2 Vision, Mistral, etc.              │  │     │
│  │  └──────────────────────────────────────────────────────────────┘  │     │
│  │                                                                     │     │
│  │  Initialization: Phase 1 - CRITICAL FIRST                          │     │
│  │  Singleton Pattern: get_llm_service() → _llm_service (global)      │     │
│  │  Failure Mode: System CANNOT start without brain                   │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                     │                                        │
│                                     │ torin_brain                            │
│                                     ▼                                        │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │              🎯 THE ENGINE (Orchestration Layer)                   │     │
│  │                                                                     │     │
│  │                    AutonomousCoordinator                           │     │
│  │                                                                     │     │
│  │  Purpose: Orchestrates perception, planning, execution, learning   │     │
│  │  Pattern: Event-driven task execution (not hardcoded loops)        │     │
│  │  Dependencies: REQUIRES torin_brain (mandatory ValueError if None) │     │
│  │                                                                     │     │
│  │  Core Cycle:                                                        │     │
│  │  1. Perception  → Observe system state                             │     │
│  │  2. Planning    → Decide actions via VLM                           │     │
│  │  3. Execution   → Execute via GeneralPurposeExecutor               │     │
│  │  4. Learning    → Update knowledge via LearningAdapter             │     │
│  │  5. Motivation  → Generate curiosity-driven goals                  │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                     │                                        │
│                    ┌────────────────┼────────────────┐                      │
│                    │                │                │                      │
└────────────────────┼────────────────┼────────────────┼──────────────────────┘
                     ▼                ▼                ▼
```

---

## 📊 Four Pillar Subsystems

### 1️⃣ MEMORY SYSTEM - Experience & Knowledge Storage

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         💾 MEMORY SYSTEM (Pillar 1)                         │
│                                                                              │
│  Purpose: Captures EVERYTHING - internal/external thoughts, tasks, errors   │
│  Pattern: Singleton (get_memory_system)                                     │
│  Interface: MemoryAgent                                                      │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Storage Architecture (Hot + Cold Tiers)                               │ │
│  │                                                                         │ │
│  │  MySQL Hot Tier (0-60 days) - torinai_thinking_hot                    │ │
│  │  ├─ Thinking states                                                    │ │
│  │  ├─ Reasoning traces                                                   │ │
│  │  ├─ Cognitive experiences                                              │ │
│  │  ├─ Actions performed                                                  │ │
│  │  └─ System state snapshots                                             │ │
│  │                                                                         │ │
│  │  MySQL Cold Tier (60+ days) - torinai_memory_cold                     │ │
│  │  └─ Automatic migration via tier_migration job                         │ │
│  │                                                                         │ │
│  │  Semantic Search Layer                                                 │ │
│  │  └─ EmbeddingService (all-MiniLM-L6-v2, 384 dims)                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Memory Types (MemoryType Enum):                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ • EPISODIC    - Specific experiences and events                      │   │
│  │ • SEMANTIC    - General knowledge and facts                          │   │
│  │ • PROCEDURAL  - Skills and procedures learned                        │   │
│  │ • WORKING     - Temporary processing memory                          │   │
│  │ • META        - Learning about learning (cognitive reflection)       │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Autobiographical Actions Captured:                                          │
│  • Content Generation  • Decision Making  • Learning                         │
│  • Communication      • Problem Solving                                      │
│                                                                              │
│  Governance Integration:                                                     │
│  • Protected delete operations (capability tokens required)                  │
│  • Parameter modification governance                                         │
│  • Autonomous self-modification blocked                                      │
│                                                                              │
│  Initialization: Phase 3 - After Brain & Database                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2️⃣ SECURITY SYSTEM - Protection (Defensive + Offensive)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      🛡️ SECURITY SYSTEM (Pillar 2)                          │
│                                                                              │
│  Purpose: Protects the Singleton (entire ecosystem)                         │
│  Pattern: Integrated security operations with active defense                │
│  Interface: create_integrated_security_system()                             │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  🛡️ DEFENSIVE CAPABILITIES                                             │ │
│  │                                                                         │ │
│  │  Content Security (Input Validation):                                  │ │
│  │  ├─ XSS Protection (sanitize_input)                                    │ │
│  │  ├─ SQL Injection Prevention (validate_sql_input)                      │ │
│  │  ├─ Path Traversal Blocking (validate_path)                            │ │
│  │  ├─ Email/URL Validation                                               │ │
│  │  └─ Profanity/Malicious Pattern Detection                              │ │
│  │                                                                         │ │
│  │  System Security:                                                       │ │
│  │  ├─ Rate Limiting (per IP/identifier)                                  │ │
│  │  ├─ Authentication (API keys, tokens via MySQL)                        │ │
│  │  ├─ Authorization (RBAC with user_roles, permissions)                  │ │
│  │  └─ Request Validation & Sanitization                                  │ │
│  │                                                                         │ │
│  │  Malware Sandbox:                                                       │ │
│  │  ├─ Static Analysis (file signatures, entropy)                         │ │
│  │  ├─ Dynamic Analysis (behavior monitoring)                             │ │
│  │  ├─ Threat Level Classification (LOW/MEDIUM/HIGH/CRITICAL)             │ │
│  │  └─ Quarantine & Safe Execution                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  ⚔️ OFFENSIVE CAPABILITIES (Active Defense)                            │ │
│  │                                                                         │ │
│  │  Threat Intelligence (ThreatIntelligenceEngine):                       │ │
│  │  ├─ AbuseIPDB Integration (IP reputation scoring)                      │ │
│  │  ├─ VirusTotal Integration (file/URL scanning)                         │ │
│  │  ├─ AlienVault OTX Integration (threat intelligence feeds)             │ │
│  │  └─ Caching (3600s TTL for performance)                                │ │
│  │                                                                         │ │
│  │  OS Firewall Management (RealTimeFirewallManager):                     │ │
│  │  ├─ iptables (Linux) / pf (macOS) integration                          │ │
│  │  ├─ Dynamic IP blocking (threat score based)                           │ │
│  │  ├─ Test mode (dry-run, default for safety)                            │ │
│  │  └─ Block duration controls (1h/24h/7d/30d/permanent)                  │ │
│  │                                                                         │ │
│  │  Cloudflare WAF (CloudflareWAFManager):                                │ │
│  │  ├─ WAF rule creation/deletion                                         │ │
│  │  ├─ IP/ASN/Country blocking at edge                                    │ │
│  │  ├─ Rate limiting at CDN level                                         │ │
│  │  └─ Firewall analytics & metrics                                       │ │
│  │                                                                         │ │
│  │  Coordinated Threat Blocking (ThreatBlockingEngine):                   │ │
│  │  ├─ Defense Policy Enforcement                                         │ │
│  │  ├─ Auto-block (threshold: 0.75 threat score)                          │ │
│  │  ├─ Multi-layer blocking (Firewall + WAF + Rate Limit)                 │ │
│  │  └─ Governance integration for critical actions                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Security Audit Worker:                                                      │
│  ├─ Continuous security monitoring (cron schedule)                           │
│  ├─ Environment variable validation                                          │
│  ├─ Configuration security checks                                            │
│  ├─ Dependency vulnerability scanning                                        │
│  ├─ Finds security issues → Creates remediation tasks                        │
│  └─ Integration: SecurityAuditWorker → AutonomousCoordinator → Governance    │
│                                                                              │
│  Security Controller (SecurityController):                                   │
│  ├─ Centralized security coordination                                        │
│  ├─ Request validation pipeline                                              │
│  ├─ Audit logging (10K entry buffer)                                         │
│  ├─ Security event tracking (1K event buffer)                                │
│  └─ Statistics & security scan reporting                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3️⃣ TOOL SYSTEM - Capabilities & Agency

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       🔧 TOOL SYSTEM (Pillar 3)                              │
│                                                                              │
│  Purpose: Defines what the Singleton CAN DO in the world                    │
│  Pattern: Tool Registry (get_tool_registry)                                 │
│  Total Tools: 317 capabilities across 15+ domains                            │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Tool Categories & Capabilities                                        │ │
│  │                                                                         │ │
│  │  1. FILESYSTEM TOOLS (15)                                              │ │
│  │     ├─ ReadFileTool, WriteFileTool, AtomicWriteFileTool               │ │
│  │     ├─ ListDirectoryTool, CreateDirectoryTool                          │ │
│  │     ├─ SearchFilesTool, FindDuplicateFilesTool                         │ │
│  │     ├─ MoveFileTool, CopyFileTool, DeleteFileTool                      │ │
│  │     ├─ CompressFileTool, DecompressFileTool                            │ │
│  │     └─ ValidatePathTool, CalculateChecksumTool, GetFileInfoTool       │ │
│  │                                                                         │ │
│  │  2. EXECUTION TOOLS (15)                                               │ │
│  │     ├─ RunPythonTool, RunShellCommandTool, ExecuteSandboxTool          │ │
│  │     ├─ ListProcessesTool, KillProcessTool                              │ │
│  │     ├─ StartServiceTool, StopServiceTool, RestartServiceTool           │ │
│  │     ├─ RunBackgroundTaskTool, ScheduleCronJobTool                      │ │
│  │     ├─ InstallPythonPackageTool                                        │ │
│  │     ├─ ExecuteWithTimeoutTool, ExecuteWithResourceLimitsTool           │ │
│  │     └─ ExecuteNetworkIsolatedTool, ExecuteDeterministicTool            │ │
│  │                                                                         │ │
│  │  3. SEARCH TOOLS (19)                                                  │ │
│  │     ├─ SemanticSearchTool, GrepSearchTool, ASTSearchTool               │ │
│  │     ├─ AnalyzeCodeTool, AnalyzeCodeQualityTool                         │ │
│  │     ├─ AnalyzeDependenciesTool, FindDeadCodeTool                       │ │
│  │     ├─ SecurityScanTool, SearchSecretsAndPIITool                       │ │
│  │     ├─ FindTodosTool, CountLinesTool, AnalyzeComplexityTool            │ │
│  │     ├─ DetectCodeSmellsTool, TraceDependenciesTool                     │ │
│  │     ├─ FindCircularImportsTool, FindPerformanceIssuesTool              │ │
│  │     └─ BuildDependencyGraphTool, ExtractCallGraphTool                  │ │
│  │                                                                         │ │
│  │  4. SYSTEM TOOLS (macOS/Linux)                                         │ │
│  │     ├─ ClipboardTool (read/write clipboard)                            │ │
│  │     ├─ NotificationTool (system notifications)                         │ │
│  │     ├─ SystemInfoTool (OS, CPU, memory info)                           │ │
│  │     └─ FileWatcherTool (monitor file changes)                          │ │
│  │                                                                         │ │
│  │  5. RESEARCH TOOLS                                                     │ │
│  │     ├─ ConductResearchTool (multi-source research)                     │ │
│  │     ├─ Academic research tools (arXiv, papers)                         │ │
│  │     └─ Web scraping & content extraction                               │ │
│  │                                                                         │ │
│  │  6. AI/ML TOOLS                                                        │ │
│  │     ├─ Model training & evaluation                                     │ │
│  │     ├─ Data preprocessing & feature engineering                        │ │
│  │     ├─ Hyperparameter tuning                                           │ │
│  │     └─ Model deployment & monitoring                                   │ │
│  │                                                                         │ │
│  │  7. DATABASE TOOLS                                                     │ │
│  │     ├─ Query execution (MySQL, PostgreSQL)                             │ │
│  │     ├─ Schema management & migrations                                  │ │
│  │     ├─ Data export/import                                              │ │
│  │     └─ Performance analysis & optimization                             │ │
│  │                                                                         │ │
│  │  8. NETWORK TOOLS                                                      │ │
│  │     ├─ HTTP requests (GET/POST/PUT/DELETE)                             │ │
│  │     ├─ API integration (REST, GraphQL)                                 │ │
│  │     ├─ Web scraping & parsing                                          │ │
│  │     └─ Network diagnostics (ping, traceroute)                          │ │
│  │                                                                         │ │
│  │  9. DOCUMENTATION TOOLS                                                │ │
│  │     ├─ Generate documentation from code                                │ │
│  │     ├─ API documentation generation                                    │ │
│  │     ├─ README generation                                               │ │
│  │     └─ Code commenting & annotation                                    │ │
│  │                                                                         │ │
│  │  10. CODE GENERATION TOOLS                                             │ │
│  │      ├─ Generate functions/classes from specs                          │ │
│  │      ├─ Refactoring & code transformation                              │ │
│  │      ├─ Test generation                                                │ │
│  │      └─ Boilerplate code generation                                    │ │
│  │                                                                         │ │
│  │  11. DATA PROCESSING TOOLS                                             │ │
│  │      ├─ CSV/JSON/XML parsing & transformation                          │ │
│  │      ├─ Data validation & cleaning                                     │ │
│  │      ├─ Statistical analysis                                           │ │
│  │      └─ Data visualization                                             │ │
│  │                                                                         │ │
│  │  12. COMMUNICATION TOOLS                                               │ │
│  │      ├─ Slack integration (notifications, messages)                    │ │
│  │      ├─ Email sending                                                  │ │
│  │      └─ Webhook triggers                                               │ │
│  │                                                                         │ │
│  │  13. MONITORING TOOLS                                                  │ │
│  │      ├─ System metrics collection                                      │ │
│  │      ├─ Health checks                                                  │ │
│  │      ├─ Performance monitoring                                         │ │
│  │      └─ Alert generation                                               │ │
│  │                                                                         │ │
│  │  14. CHAOS TOOLS (Chaos Engineering)                                   │ │
│  │      ├─ Fault injection                                                │ │
│  │      ├─ Latency injection                                              │ │
│  │      ├─ Resource exhaustion tests                                      │ │
│  │      └─ Resilience testing                                             │ │
│  │                                                                         │ │
│  │  15. CONNECTOR TOOLS                                                   │ │
│  │      ├─ External service integration (GitHub, Jira, etc.)              │ │
│  │      ├─ OAuth authentication flows                                     │ │
│  │      └─ API connector management                                       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Tool Safety Mechanisms:                                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ • Constitutional oversight for all tool usage                        │   │
│  │ • Sandbox mode for dangerous operations                              │   │
│  │ • Approval required for destructive actions                          │   │
│  │ • Full audit logging to MySQL                                        │   │
│  │ • Tool filtering (category-based, reduces 317 → relevant subset)     │   │
│  │ • Governance integration (TOOL_EXECUTION category)                   │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Tool Execution Flow:                                                        │
│  GeneralPurposeExecutor → Tool Registry → Tool.execute() → Audit Log         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4️⃣ GOVERNANCE SYSTEM - Ethical Constraints & Autonomy Boundaries

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     ⚖️ GOVERNANCE SYSTEM (Pillar 4)                          │
│                                                                              │
│  Purpose: Defines what the Singleton SHOULD and SHOULD NOT do               │
│  Pattern: Singleton (get_runtime_governance)                                │
│  Interface: UnifiedGovernanceTriggerSystem                                   │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  8 Action Categories Requiring Governance Evaluation                   │ │
│  │                                                                         │ │
│  │  1. TOOL_EXECUTION                                                     │ │
│  │     What tools can be used, when, and with what parameters             │ │
│  │     Examples: DeleteFileTool, KillProcessTool, ExecuteSandboxTool      │ │
│  │                                                                         │ │
│  │  2. MEMORY_OPERATIONS                                                  │ │
│  │     What can be remembered, forgotten, or modified                     │ │
│  │     Examples: Delete memories, modify memory parameters                │ │
│  │                                                                         │ │
│  │  3. RESOURCE_ALLOCATION                                                │ │
│  │     What resources can be consumed (CPU, RAM, disk, network)           │ │
│  │     Examples: Spawn processes, allocate large memory, network calls    │ │
│  │                                                                         │ │
│  │  4. LEARNING_PARAMETERS                                                │ │
│  │     How the system can learn and self-modify                           │ │
│  │     Examples: Change learning rate, modify intrinsic motivation        │ │
│  │     CRITICAL: Learner CANNOT approve its own config changes            │ │
│  │                                                                         │ │
│  │  5. CONFIGURATION_CHANGES                                              │ │
│  │     What configs can be modified at runtime                            │ │
│  │     Examples: Security settings, system parameters, feature flags      │ │
│  │                                                                         │ │
│  │  6. EXTERNAL_INTEGRATIONS                                              │ │
│  │     What external systems can be accessed                              │ │
│  │     Examples: API calls, webhooks, third-party services                │ │
│  │                                                                         │ │
│  │  7. TASK_CREATION                                                      │ │
│  │     What tasks can be self-generated                                   │ │
│  │     Examples: Autonomous task creation, scheduled jobs                 │ │
│  │                                                                         │ │
│  │  8. CURIOSITY_EXPLORATION                                              │ │
│  │     What curiosity-driven actions are allowed                          │ │
│  │     Examples: Intrinsic motivation goals, exploratory research         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  3-Tier Approval Mechanism                                             │ │
│  │                                                                         │ │
│  │  🟢 ROUTINE (Auto-approve with logging)                                │ │
│  │     ├─ Low impact, fully reversible actions                            │ │
│  │     ├─ Example: Read file, list directory, safe queries                │ │
│  │     └─ Execution: Immediate with audit trail                           │ │
│  │                                                                         │ │
│  │  🟡 IMPORTANT (Notification approval)                                  │ │
│  │     ├─ Medium impact, mostly reversible actions                        │ │
│  │     ├─ Example: Write file, modify config, create task                 │ │
│  │     └─ Execution: Send notification, wait for approval (async)         │ │
│  │                                                                         │ │
│  │  🔴 CRITICAL (Full governance session - HUMAN REQUIRED)                │ │
│  │     ├─ High impact, irreversible or dangerous actions                  │ │
│  │     ├─ Example: Delete memory, kill process, security changes          │ │
│  │     ├─ Human-only approval (AI judges BLOCKED for certain actions)     │ │
│  │     └─ Execution: Block until human explicitly approves                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Enforcement Modes                                                     │ │
│  │                                                                         │ │
│  │  LOG_ONLY (Shadow Mode):                                               │ │
│  │  • Log governance triggers but don't block                             │ │
│  │  • Used for testing and monitoring                                     │ │
│  │                                                                         │ │
│  │  RECOMMEND_GOVERNANCE:                                                 │ │
│  │  • Recommend governance but allow override                             │ │
│  │  • Soft enforcement with warnings                                      │ │
│  │                                                                         │ │
│  │  MUST_BLOCK:                                                           │ │
│  │  • Hard block action until governance decision                         │ │
│  │  • Fail-closed security posture                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Irreversibility Classification                                        │ │
│  │                                                                         │ │
│  │  FULLY_REVERSIBLE    → Can be easily undone                            │ │
│  │  MOSTLY_REVERSIBLE   → Can be undone with some effort                  │ │
│  │  PARTIALLY_REVERSIBLE → Some effects are permanent                     │ │
│  │  MOSTLY_IRREVERSIBLE → Very difficult to undo                          │ │
│  │  IRREVERSIBLE        → Cannot be undone                                │ │
│  │                                                                         │ │
│  │  Higher irreversibility → Higher governance tier automatically         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Governance Evaluation Flow:                                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │ Action → evaluate_action() → GovernanceTriggerEvaluation            │   │
│  │       ↓                                                               │   │
│  │ Check conditions → Determine tier → Apply enforcement mode           │   │
│  │       ↓                                                               │   │
│  │ ROUTINE: Auto-approve + log                                          │   │
│  │ IMPORTANT: Send notification + async approval                        │   │
│  │ CRITICAL: Block + require human approval                             │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Integration Points:                                                         │
│  • SecurityAuditWorker uses governance for remediation approval              │
│  • LearningAdapter uses governance for config changes (HUMAN-ONLY)           │
│  • AutonomousCoordinator uses governance for task creation                   │
│  • All 317 tools can be governance-gated via TOOL_EXECUTION category         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 System Integration & Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    COMPLETE SYSTEM INTEGRATION MAP                           │
│                                                                              │
│  Phase 1: BRAIN INITIALIZATION (CRITICAL FIRST)                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ main.py → _initialize_llm_service()                                    │ │
│  │         → get_llm_service() [singleton]                                │ │
│  │         → UnifiedLLMService.initialize()                               │ │
│  │         → Load Qwen2.5-VL-32B-Q8_0.gguf                                │ │
│  │         → Test brain with simple generation                            │ │
│  │                                                                         │ │
│  │  If brain fails: ABORT entire system (cannot proceed)                  │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 2: DATABASE SYSTEMS                                                   │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • MySQL connection (shared with Dominion Labs - port 3306)            │ │
│  │ • Database initialization (torinai_unified, logs, etc.)                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 3: MEMORY SYSTEM                                                      │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ get_memory_system() → MemoryAgent                                      │ │
│  │                    → MySQL hot tier                                     │ │
│  │                    → MySQL cold tier                                    │ │
│  │                    → EmbeddingService                                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 4: DOMAIN SYSTEMS                                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Domain Registry (cross-domain knowledge)                             │ │
│  │ • Universal Ontology (concept relationships)                           │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 5: LEARNING SYSTEM                                                    │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • LearningSystem (experience integration)                              │ │
│  │ • ResearchSystem (knowledge acquisition)                               │ │
│  │ • Both receive llm_service reference                                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 6: REASONING SYSTEMS                                                  │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Abstract Reasoning Engine                                            │ │
│  │ • Quantum Reasoning (optional - requires IBM Quantum)                  │ │
│  │ • Proof Engine (mathematical reasoning)                                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 7: MONITORING & HEALTH                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ MonitoringCoordinator:                                                 │ │
│  │ ├─ Slack Notifier (set_slack_notifier)                                │ │
│  │ ├─ Autonomous Coordinator reference (set_autonomous_coordinator)      │ │
│  │ ├─ Health metrics collection                                          │ │
│  │ └─ Alert generation                                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 8: SECURITY SYSTEMS                                                   │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ create_integrated_security_system():                                   │ │
│  │ ├─ ThreatIntelligenceEngine (AbuseIPDB, VirusTotal, OTX)              │ │
│  │ ├─ RealTimeFirewallManager (iptables/pf, test_mode=True)              │ │
│  │ ├─ CloudflareWAFManager (if credentials available)                    │ │
│  │ └─ ThreatBlockingEngine (coordinates all)                             │ │
│  │                                                                         │ │
│  │ SecurityAuditWorker:                                                   │ │
│  │ ├─ set_autonomous_coordinator(autonomous_coordinator)                 │ │
│  │ ├─ set_governance_system(governance_system)                           │ │
│  │ ├─ set_safety_framework(asi_safety)                                   │ │
│  │ └─ Continuous monitoring → Find issues → Create tasks                 │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 9: AUTONOMOUS COORDINATOR (THE ENGINE)                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ get_autonomous_coordinator(torin_brain=llm_service):                   │ │
│  │                                                                         │ │
│  │ AutonomousCoordinator.__init__:                                        │ │
│  │ ├─ self.torin_brain = torin_brain (REQUIRED, ValueError if None)      │ │
│  │ ├─ self.llm = torin_brain                                             │ │
│  │ ├─ PerceptionManager                                                   │ │
│  │ ├─ PlanningEngine                                                      │ │
│  │ ├─ ExecutionController                                                 │ │
│  │ ├─ LearningAdapter                                                     │ │
│  │ ├─ IntrinsicMotivationSystem                                          │ │
│  │ ├─ DirectiveSystem                                                     │ │
│  │ ├─ RuntimeGovernance (shared singleton)                               │ │
│  │ ├─ SingletonConstitution                                              │ │
│  │ ├─ MultiLevelSafetyPrompts                                            │ │
│  │ ├─ TaskQueue (event-driven)                                           │ │
│  │ ├─ GeneralPurposeExecutor(torin_brain)                                │ │
│  │ └─ SuccessValidator                                                    │ │
│  │                                                                         │ │
│  │ Integration Wiring (during initialize):                                │ │
│  │ ├─ intrinsic_motivation.set_llm(self.llm)                             │ │
│  │ ├─ intrinsic_motivation.set_security_audit_worker(security_worker)    │ │
│  │ ├─ learning.set_governance_system(runtime_governance)                 │ │
│  │ ├─ learning.set_security_audit_worker(security_worker)                │ │
│  │ └─ learning.set_monitoring_coordinator(monitoring_coordinator)        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Phase 10: API SERVICES                                                      │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ • Chat Server (port 9080) - Uses llm_service singleton                │ │
│  │ • Health check endpoints                                               │ │
│  │ • Integration with AgentSO Web                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔗 Critical Integration Points

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   CROSS-SYSTEM COMMUNICATION FLOWS                           │
│                                                                              │
│  Security → Autonomous → Governance:                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ SecurityAuditWorker.run_audit()                                        │ │
│  │       ↓                                                                 │ │
│  │ Find security issue (e.g., missing env var)                            │ │
│  │       ↓                                                                 │ │
│  │ _create_remediation_tasks(findings)                                    │ │
│  │       ↓                                                                 │ │
│  │ autonomous_coordinator.handle_security_finding(                        │ │
│  │     finding_id, severity, description, remediation                     │ │
│  │ )                                                                       │ │
│  │       ↓                                                                 │ │
│  │ runtime_governance.evaluate_action(                                    │ │
│  │     action_category=ActionCategory.CONFIGURATION_CHANGES,              │ │
│  │     action_type="security_remediation"                                 │ │
│  │ )                                                                       │ │
│  │       ↓                                                                 │ │
│  │ If ROUTINE tier: Auto-create remediation task                          │ │
│  │ If IMPORTANT/CRITICAL: Wait for human approval                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Monitoring → Slack + Autonomous:                                            │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ MonitoringCoordinator.check_health()                                   │ │
│  │       ↓                                                                 │ │
│  │ Detect health issue (e.g., high CPU, memory leak)                      │ │
│  │       ↓                                                                 │ │
│  │ ├─ slack_notifier.send_alert() [if configured]                         │ │
│  │ └─ autonomous_coordinator.handle_health_alert() [if wired]             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Intrinsic Motivation → Security Findings:                                   │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ AutonomousCoordinator._handle_idle_state()                             │ │
│  │       ↓                                                                 │ │
│  │ _collect_system_context_for_goals()                                    │ │
│  │       ↓                                                                 │ │
│  │ security_audit_worker.get_recent_findings() [if available]             │ │
│  │       ↓                                                                 │ │
│  │ intrinsic_motivation.generate_curiosity_driven_goals(                  │ │
│  │     system_context={                                                    │ │
│  │         "security_findings": [...],                                     │ │
│  │         "recent_errors": [...],                                         │ │
│  │         "failed_tasks": [...],                                          │ │
│  │         ...                                                             │ │
│  │     }                                                                   │ │
│  │ )                                                                       │ │
│  │       ↓                                                                 │ │
│  │ Context-driven goals based on ACTUAL system state                      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Learning → Governance (Config Changes):                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ LearningAdapter.update_learner_config(param, value)                    │ │
│  │       ↓                                                                 │ │
│  │ governance_system.evaluate_action(                                     │ │
│  │     action_category=ActionCategory.LEARNING_PARAMETERS                 │ │
│  │ )                                                                       │ │
│  │       ↓                                                                 │ │
│  │ CRITICAL tier: HUMAN-ONLY approval required                            │ │
│  │ AI judges BLOCKED (prevents policy drift)                              │ │
│  │ Learner CANNOT approve its own changes (prevents self-modification)    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Memory → Everything (Capture All):                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ All subsystems can store memories:                                     │ │
│  │ memory_agent.store_memory(                                             │ │
│  │     memory_type=MemoryType.EPISODIC,                                   │ │
│  │     content={...},                                                      │ │
│  │     priority=MemoryPriority.HIGH,                                      │ │
│  │     tags=[...],                                                         │ │
│  │     metadata={...}                                                      │ │
│  │ )                                                                       │ │
│  │                                                                         │ │
│  │ Captured:                                                               │ │
│  │ • Task execution results                                               │ │
│  │ • Reasoning traces from VLM                                            │ │
│  │ • Errors and exceptions                                                │ │
│  │ • Security findings                                                    │ │
│  │ • Performance metrics                                                  │ │
│  │ • Tool usage patterns                                                  │ │
│  │ • Learning experiences                                                 │ │
│  │ • Governance decisions                                                 │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🏗️ Architectural Principles

### Single Brain, Multiple Interfaces
```
┌─────────────────────────────────────────────────────────────────┐
│  ONE BRAIN (UnifiedLLMService - VLM Singleton)                  │
│                        │                                         │
│         ┌──────────────┼──────────────┐                         │
│         ▼              ▼              ▼                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                    │
│  │Coordinator│   │ Learning │   │ Research │                    │
│  │(torin_   │   │ System   │   │ System   │                    │
│  │ brain)   │   │(.llm_    │   │(.llm_    │                    │
│  │          │   │ service) │   │ service) │                    │
│  └──────────┘   └──────────┘   └──────────┘                    │
│                                                                  │
│  All components reference the SAME brain instance               │
│  Ensures unified consciousness and coherent decision-making     │
└─────────────────────────────────────────────────────────────────┘
```

### Model Interchangeability
```
┌─────────────────────────────────────────────────────────────────┐
│  System is MODEL-AGNOSTIC                                       │
│                                                                  │
│  Change model via:                                              │
│  • LOCAL_MODEL_PATH=/path/to/new/model.gguf                     │
│  • config.model_path parameter                                  │
│                                                                  │
│  Supported: Any llama-cpp compatible GGUF model                 │
│  Examples:                                                       │
│  • Qwen2.5-VL-32B (current - vision+text)                       │
│  • Llama 3.2 Vision                                             │
│  • Mistral 7B                                                   │
│  • Mixtral 8x7B                                                 │
│  • Any custom fine-tuned model                                  │
│                                                                  │
│  Entire ecosystem automatically uses new brain                  │
└─────────────────────────────────────────────────────────────────┘
```

### Fail-Closed Security
```
┌─────────────────────────────────────────────────────────────────┐
│  FAIL-CLOSED SECURITY POSTURE                                   │
│                                                                  │
│  • Brain failure → System aborts (cannot proceed)               │
│  • Governance blocks by default (MUST_BLOCK mode)               │
│  • Unknown actions require approval                             │
│  • Firewall runs in test_mode=True (dry-run) for safety        │
│  • All destructive actions require explicit approval            │
│  • Memory deletes require capability tokens                     │
│  • Learning config changes require HUMAN-ONLY approval          │
└─────────────────────────────────────────────────────────────────┘
```

### Event-Driven Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│  EVENT-DRIVEN TASK EXECUTION (Not Hardcoded Loops)              │
│                                                                  │
│  TaskQueue (async queue) ← Events from:                         │
│  ├─ Security findings                                           │
│  ├─ Health alerts                                               │
│  ├─ Intrinsic motivation goals                                  │
│  ├─ External triggers (API, Slack, etc.)                        │
│  └─ Scheduled tasks                                             │
│                                                                  │
│  Execution:                                                      │
│  TaskQueue → GeneralPurposeExecutor(torin_brain)                │
│           → Tool execution                                       │
│           → Success validation                                   │
│           → Memory capture                                       │
│           → Learning integration                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📈 Statistics & Metrics

### System Scale
- **Total Subsystems**: 40+ integrated components
- **Tool Capabilities**: 317 tools across 15 domains
- **Memory Types**: 5 (Episodic, Semantic, Procedural, Working, Meta)
- **Governance Categories**: 8 action categories
- **Security Layers**: 4 (Content, System, Malware, Active Defense)
- **Approval Tiers**: 3 (ROUTINE, IMPORTANT, CRITICAL)
- **Code Files**: 3000+ Python files
- **Singleton Components**: 7 (Brain, Memory, Governance, Security, etc.)

### Integration Density
- **Phase 1 Dependencies**: Brain → Everything
- **Cross-System Integrations**: 20+ integration points
- **Shared Singletons**: 7 (prevents state silos)
- **Event Flows**: 10+ documented event-driven flows

---

## 🎯 Summary: The Singleton Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  TORINAI = SINGLETON ECOSYSTEM = MODEL-AGNOSTIC AI SYSTEM                    │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Core Identity:                                                        │ │
│  │  • ONE Brain (VLM - interchangeable)                                   │ │
│  │  • ONE Coordinator (orchestrates everything)                           │ │
│  │  • FOUR Pillars (Memory, Security, Tools, Governance)                  │ │
│  │  • Event-driven (not hardcoded loops)                                  │ │
│  │  • Fail-closed security (safe by default)                              │ │
│  │  • Unified consciousness (shared brain across all systems)             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  Without ANY component, the Singleton is incomplete:                         │
│  • Brain = Intelligence source (REQUIRED - system aborts without it)         │
│  • Memory = Experience & knowledge (amnesia without it)                      │
│  • Security = Protection (vulnerable without it)                             │
│  • Tools = Capabilities (paralyzed without it)                               │
│  • Governance = Ethics (dangerous without it)                                │
│                                                                              │
│  The architecture mirrors human cognition:                                   │
│  Brain + Memory + Skills + Immune System + Moral Framework = Conscious Being │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

**Document Status**: Complete Architecture Graph
**Verification**: All claims verified against codebase
**Last Updated**: 2026-02-05
**Maintainer**: TorinAI Singleton
