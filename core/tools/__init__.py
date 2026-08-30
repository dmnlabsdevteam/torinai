#!/usr/bin/env python3
"""
Torin AI Tool System
====================
Provides tool/function calling capabilities for the Singleton.

Available Tools:
- Filesystem: read, write, list, search files
- Execution: run Python, shell commands, sandbox testing
- Search: semantic search, grep, code analysis
- macOS: clipboard, notifications, system info

Safety:
- Constitutional oversight for all tool usage
- Sandbox mode for dangerous operations
- Approval required for destructive actions
- Full audit logging

Author: Torin AI Team
"""

from .tool_registry import (
    Tool,
    ToolParameter,
    ToolResult,
    ToolRegistry,
    get_tool_registry
)

from .filesystem_tools import (
    ReadFileTool,
    WriteFileTool,
    ListDirectoryTool,
    CreateDirectoryTool,
    SearchFilesTool,
    MoveFileTool,
    CopyFileTool,
    DeleteFileTool,
    AtomicWriteFileTool,
    ValidatePathTool,
    CalculateChecksumTool,
    GetFileInfoTool,
    CompressFileTool,
    DecompressFileTool,
    FindDuplicateFilesTool,
    SyncDirectoryTool
)

from .execution_tools import (
    RunPythonTool,
    RunShellCommandTool,
    ExecuteSandboxTool,
    ListProcessesTool,
    KillProcessTool,
    StartServiceTool,
    StopServiceTool,
    RestartServiceTool,
    GetProcessInfoTool,
    RunBackgroundTaskTool,
    ScheduleCronJobTool,
    InstallPythonPackageTool,
    ExecuteWithTimeoutTool,
    ExecuteWithResourceLimitsTool,
    ExecuteNetworkIsolatedTool,
    ExecuteDeterministicTool,
    ExecuteWithArtifactCaptureTool
)

from .search_tools import (
    SemanticSearchTool,
    GrepSearchTool,
    AnalyzeCodeTool,
    AnalyzeCodeQualityTool,
    AnalyzeDependenciesTool,
    FindDeadCodeTool,
    SecurityScanTool,
    FindTodosTool,
    CountLinesTool,
    AnalyzeComplexityTool,
    DetectCodeSmellsTool,
    TraceDependenciesTool,
    FindCircularImportsTool,
    AnalyzeTestCoverageReportTool,
    FindPerformanceIssuesTool,
    CheckCodeStyleConsistencyTool,
    ASTSearchTool,
    BuildDependencyGraphTool,
    ExtractCallGraphTool,
    SearchSecretsAndPIITool
)

from .system_tools import (
    ClipboardTool,
    NotificationTool,
    SystemInfoTool,
    FileWatcherTool,
    ListUsbDevicesTool,
    InstalledSoftwareTool
)

from .research_tools import (
    ConductResearchTool,
    SearchAcademicTool,
    SearchDataTool,
    SearchNewsTool
)

from .academic_tools import (
    AnalyzeResearchPaperTool,
    GenerateCitationTool,
    SynthesizeLiteratureTool,
    ExtractPaperMetadataTool,
    AnalyzeResearchDataTool,
    GenerateLatexDocumentTool,
    CreateResearchGraphTool,
    GenerateArchitectureDiagramTool,
    CreateFlowchartTool,
    FetchPaperByDOITool,
    FetchPaperByArxivTool,
    ValidateBibliographyTool,
    ExportBibliographyCSLTool,
    LinkClaimToEvidenceTool,
    GenerateArtifactManifestTool
)

from .security_tools import (
    # Encryption & Cryptography
    EncryptFileTool,
    DecryptFileTool,
    GeneratePasswordTool,
    HashDataTool,
    ValidateCertificateTool,
    ScanSecretsTool,
    # Active Defense & Threat Intelligence
    CheckIPThreatIntelligenceTool,
    BlockIPAddressTool,
    UnblockIPAddressTool,
    GetActiveBlocksTool,
    CreateWAFRuleTool,
    ApplyRateLimitTool,
    BlockCountryTool,
    GetSecurityMetricsTool,
    GetBlockHistoryTool,
    AddInternalThreatTool,
    SanitizeInputTool,
    # Defensive Security & Intrusion Detection
    DetectIntrusionTool,
    AnalyzeAnomalyTool,
    MonitorLogsTool,
    DetectBruteForceTool,
    AnalyzeTrafficPatternTool,
    AutoRespondThreatTool,
    HuntThreatsTool,
    DetectZeroDayTool
)

from .ai_ml_tools import (
    GenerateEmbeddingTool,
    QueryMemoryTool,
    StoreMemoryTool,
    RunInferenceTool,
    AnalyzeTrainingDataTool,
    GetModelInfoTool,
    SemanticSimilarityTool,
    ExtractEntitiesTool
)

from .learning_tools import (
    ProfilePerformanceTool,
    AnalyzeCausalFeedbackTool,
    MonitorDataDriftTool,
    TriggerSelfImprovementTool,
    register_learning_tools
)

from .code_generation_tools import (
    GenerateFunctionTool,
    RefactorCodeTool,
    AddDocstringTool,
    AddTypeHintsTool,
    FormatCodeTool,
    FixLintingErrorsTool,
    GenerateTestTool,
    MigrateCodeTool,
    GenerateClassTool,
    GenerateModuleTool,
    AddLoggingTool,
    OptimizeCodeTool,
    ConvertToAsyncTool,
    ExtractMethodTool,
    InlineVariableTool,
    RenameSymbolTool,
    ImplementAlgorithmTool,
    GenerateSymbolicMathTool,
    GenerateNumericalCodeTool,
    GenerateMathProofTool,
    GenerateDesignPatternTool,
    GenerateAPIClientTool,
    ScaffoldApplicationTool,
    SynthesizeFromExamplesTool,
    GeneratePropertyTestTool,
    ApplyPatchTool,
    CompileTypecheckGateTool,
    RepositoryRefactorTool,
    LicenseAttributionCheckTool
)

from .communication_tools import (
    SendSlackMessageTool,
    PostToWebhookTool
)

from .data_processing_tools import (
    ParseJSONTool,
    ParseYAMLTool,
    ParseCSVTool,
    ConvertFormatTool,
    TransformDataTool,
    AggregateDataTool,
    MergeDatasetsTool,
    FilterDataTool,
    SortDataTool,
    DeduplicateDataTool,
    # Advanced data processing
    ParseJSONLTool,
    SchemaInferenceTool,
    PIIScrubbingTool,
    DatasetProfilingTool
)

from .database_tools import (
    MySQLQueryTool,
    MySQLTableInfoTool,
    MySQLBackupTool,
    MySQLRestoreTool,
    RedisGetTool,
    RedisSetTool,
    R2UploadTool,
    R2DownloadTool,
    # Advanced database tools
    ConnectionPoolManagerTool,
    TransactionWrapperTool,
    MigrationRunnerTool,
    RowLevelAccessControlTool,
    SafeQueryExecutorTool
)

from .documentation_tools import (
    GenerateReadmeTool,
    GenerateAPIDocsTool,
    ExtractDocstringsTool,
    GenerateChangelogTool,
    CreateDiagramTool,
    UpdateDocsTool,
    # Advanced documentation tools
    DocsBuildPreviewTool,
    VersionedDocDeploymentTool,
    ADRGeneratorTool,
    # Document generation tools
    GeneratePDFDocumentTool,
    GenerateWordDocumentTool,
    GeneratePowerPointTool,
    GenerateArchitectureDiagramTool,
    CreateFlowchartTool
)

from .monitoring_tools import (
    GetCPUUsageTool,
    GetMemoryUsageTool,
    GetDiskUsageTool,
    GetNetworkStatsTool,
    CheckMySQLHealthTool,
    GetServiceStatusTool,
    ParseLogsTool,
    QueryMetricsTool,
    CreateAlertTool,
    GetPerformanceProfileTool,
    # Advanced monitoring tools
    DistributedTracingTool,
    SLOSLIToolingTool,
    AnomalyDetectionTool,
    DashboardGeneratorTool
)

from .network_tools import (
    HttpRequestTool,
    DownloadFileTool,
    UploadFileTool,
    ParseHTMLTool,
    ExtractLinksTool,
    CheckURLStatusTool,
    DNSLookupTool,
    PingHostTool,
    PortScanTool,
    WebSocketConnectTool,
    GraphQLQueryTool,
    APICallTool
)

from .system_management_tools import (
    SetEnvironmentVariableTool,
    GetEnvironmentVariableTool,
    ModifyConfigFileTool,
    ReloadConfigTool,
    CheckDependenciesTool,
    UpdateSystemTool,
    ManageDockerTool
)

from .testing_validation_tools import (
    RunPytestTool,
    RunUnittestTool,
    CheckSyntaxTool,
    ValidateJSONTool,
    ValidateYAMLTool,
    LintPythonTool,
    TypeCheckTool,
    BenchmarkCodeTool,
    GenerateMockTool,
    RunCoverageTool,
    ValidateXMLTool,
    ValidateSchemaTool,
    LoadTestTool,
    IntegrationTestRunnerTool,
    TestDataGeneratorTool,
    # Advanced testing/validation tools
    FuzzTestingTool,
    MutationTestingTool,
    StaticSecurityAnalysisTool,
    GoldenTestHarnessTool,
    ChaosTestingTool
)

from .reasoning_tools import (
    ProveTheoremTool,
    SolveConstraintsTool,
    SolveLinearOptimizationTool,
    SimulatePDE1DTool,
    SimulateStateSpaceTool,
    RunMonteCarloTool,
)

__all__ = [
    # Core classes
    'Tool',
    'ToolParameter',
    'ToolResult',
    'ToolRegistry',
    'get_tool_registry',

    # Filesystem tools
    'ReadFileTool',
    'WriteFileTool',
    'ListDirectoryTool',
    'CreateDirectoryTool',
    'SearchFilesTool',
    'MoveFileTool',
    'CopyFileTool',
    'DeleteFileTool',
    'AtomicWriteFileTool',
    'ValidatePathTool',
    'CalculateChecksumTool',
    'GetFileInfoTool',
    'CompressFileTool',
    'DecompressFileTool',
    'FindDuplicateFilesTool',
    'SyncDirectoryTool',

    # Execution tools
    'RunPythonTool',
    'RunShellCommandTool',
    'ExecuteSandboxTool',
    'ListProcessesTool',
    'KillProcessTool',
    'StartServiceTool',
    'StopServiceTool',
    'RestartServiceTool',
    'GetProcessInfoTool',
    'RunBackgroundTaskTool',
    'ScheduleCronJobTool',
    'InstallPythonPackageTool',
    'ExecuteWithTimeoutTool',
    'ExecuteWithResourceLimitsTool',
    'ExecuteNetworkIsolatedTool',
    'ExecuteDeterministicTool',
    'ExecuteWithArtifactCaptureTool',

    # Search tools
    'SemanticSearchTool',
    'GrepSearchTool',
    'AnalyzeCodeTool',
    'AnalyzeCodeQualityTool',
    'AnalyzeDependenciesTool',
    'FindDeadCodeTool',
    'SecurityScanTool',
    'FindTodosTool',
    'CountLinesTool',
    'AnalyzeComplexityTool',
    'DetectCodeSmellsTool',
    'TraceDependenciesTool',
    'FindCircularImportsTool',
    'AnalyzeTestCoverageReportTool',
    'FindPerformanceIssuesTool',
    'CheckCodeStyleConsistencyTool',
    'ASTSearchTool',
    'BuildDependencyGraphTool',
    'ExtractCallGraphTool',
    'SearchSecretsAndPIITool',

    # System tools (cross-platform)
    'ClipboardTool',
    'NotificationTool',
    'SystemInfoTool',
    'FileWatcherTool',
    'ListUsbDevicesTool',
    'InstalledSoftwareTool',

    # Research tools
    'ConductResearchTool',
    'SearchAcademicTool',
    'SearchDataTool',
    'SearchNewsTool',

    # Academic tools
    'AnalyzeResearchPaperTool',
    'GenerateCitationTool',
    'SynthesizeLiteratureTool',
    'ExtractPaperMetadataTool',
    'AnalyzeResearchDataTool',
    'GenerateLatexDocumentTool',
    'CreateResearchGraphTool',
    'GenerateArchitectureDiagramTool',
    'CreateFlowchartTool',
    'FetchPaperByDOITool',
    'FetchPaperByArxivTool',
    'ValidateBibliographyTool',
    'ExportBibliographyCSLTool',
    'LinkClaimToEvidenceTool',
    'GenerateArtifactManifestTool',

    # Security tools - Encryption & Cryptography
    'EncryptFileTool',
    'DecryptFileTool',
    'GeneratePasswordTool',
    'HashDataTool',
    'ValidateCertificateTool',
    'ScanSecretsTool',

    # Security tools - Active Defense & Threat Intelligence
    'CheckIPThreatIntelligenceTool',
    'BlockIPAddressTool',
    'UnblockIPAddressTool',
    'GetActiveBlocksTool',
    'CreateWAFRuleTool',
    'ApplyRateLimitTool',
    'BlockCountryTool',
    'GetSecurityMetricsTool',
    'GetBlockHistoryTool',
    'AddInternalThreatTool',
    'SanitizeInputTool',

    # Security tools - Defensive Security & Intrusion Detection
    'DetectIntrusionTool',
    'AnalyzeAnomalyTool',
    'MonitorLogsTool',
    'DetectBruteForceTool',
    'AnalyzeTrafficPatternTool',
    'AutoRespondThreatTool',
    'HuntThreatsTool',
    'DetectZeroDayTool',

    # AI/ML tools
    'GenerateEmbeddingTool',
    'QueryMemoryTool',
    'StoreMemoryTool',
    'RunInferenceTool',
    'AnalyzeTrainingDataTool',
    'GetModelInfoTool',
    'SemanticSimilarityTool',
    'ExtractEntitiesTool',

    # Learning tools
    'ProfilePerformanceTool',
    'AnalyzeCausalFeedbackTool',
    'MonitorDataDriftTool',
    'TriggerSelfImprovementTool',
    'register_learning_tools',

    # Code generation tools
    'GenerateFunctionTool',
    'RefactorCodeTool',
    'AddDocstringTool',
    'AddTypeHintsTool',
    'FormatCodeTool',
    'FixLintingErrorsTool',
    'GenerateTestTool',
    'MigrateCodeTool',
    'GenerateClassTool',
    'GenerateModuleTool',
    'AddLoggingTool',
    'OptimizeCodeTool',
    'ConvertToAsyncTool',
    'ExtractMethodTool',
    'InlineVariableTool',
    'RenameSymbolTool',
    'ImplementAlgorithmTool',
    'GenerateSymbolicMathTool',
    'GenerateNumericalCodeTool',
    'GenerateMathProofTool',
    'GenerateDesignPatternTool',
    'GenerateAPIClientTool',
    'ScaffoldApplicationTool',
    'SynthesizeFromExamplesTool',
    'GeneratePropertyTestTool',
    'ApplyPatchTool',
    'CompileTypecheckGateTool',
    'RepositoryRefactorTool',
    'LicenseAttributionCheckTool',

    # Communication tools
    'SendSlackMessageTool',
    'PostToWebhookTool',

    # Data processing tools
    'ParseJSONTool',
    'ParseYAMLTool',
    'ParseCSVTool',
    'ConvertFormatTool',
    'TransformDataTool',
    'AggregateDataTool',
    'MergeDatasetsTool',
    'FilterDataTool',
    'SortDataTool',
    'DeduplicateDataTool',
    'ParseJSONLTool',
    'SchemaInferenceTool',
    'PIIScrubbingTool',
    'DatasetProfilingTool',

    # Database tools
    'MySQLQueryTool',
    'MySQLTableInfoTool',
    'MySQLBackupTool',
    'MySQLRestoreTool',
    'RedisGetTool',
    'RedisSetTool',
    'R2UploadTool',
    'R2DownloadTool',
    'ConnectionPoolManagerTool',
    'TransactionWrapperTool',
    'MigrationRunnerTool',
    'RowLevelAccessControlTool',
    'SafeQueryExecutorTool',

    # Documentation tools
    'GenerateReadmeTool',
    'GenerateAPIDocsTool',
    'ExtractDocstringsTool',
    'GenerateChangelogTool',
    'CreateDiagramTool',
    'UpdateDocsTool',
    'DocsBuildPreviewTool',
    'VersionedDocDeploymentTool',
    'ADRGeneratorTool',
    # Real document generation
    'GeneratePDFDocumentTool',
    'GenerateWordDocumentTool',
    'GeneratePowerPointTool',
    'GenerateArchitectureDiagramTool',
    'CreateFlowchartTool',

    # Monitoring tools
    'GetCPUUsageTool',
    'GetMemoryUsageTool',
    'GetDiskUsageTool',
    'GetNetworkStatsTool',
    'CheckMySQLHealthTool',
    'GetServiceStatusTool',
    'ParseLogsTool',
    'QueryMetricsTool',
    'CreateAlertTool',
    'GetPerformanceProfileTool',
    'DistributedTracingTool',
    'SLOSLIToolingTool',
    'AnomalyDetectionTool',
    'DashboardGeneratorTool',

    # Network tools
    'HttpRequestTool',
    'DownloadFileTool',
    'UploadFileTool',
    'ParseHTMLTool',
    'ExtractLinksTool',
    'CheckURLStatusTool',
    'DNSLookupTool',
    'PingHostTool',
    'PortScanTool',
    'WebSocketConnectTool',
    'GraphQLQueryTool',
    'APICallTool',

    # System management tools
    'SetEnvironmentVariableTool',
    'GetEnvironmentVariableTool',
    'ModifyConfigFileTool',
    'ReloadConfigTool',
    'CheckDependenciesTool',
    'UpdateSystemTool',
    'ManageDockerTool',

    # Testing & validation tools
    'RunPytestTool',
    'RunUnittestTool',
    'CheckSyntaxTool',
    'ValidateJSONTool',
    'ValidateYAMLTool',
    'LintPythonTool',
    'TypeCheckTool',
    'BenchmarkCodeTool',
    'GenerateMockTool',
    'RunCoverageTool',
    'ValidateXMLTool',
    'ValidateSchemaTool',
    'LoadTestTool',
    'IntegrationTestRunnerTool',
    'TestDataGeneratorTool',
    'FuzzTestingTool',
    'MutationTestingTool',
    'StaticSecurityAnalysisTool',
    'GoldenTestHarnessTool',
    'ChaosTestingTool'

    # Reasoning / simulation / optimization tools
    'ProveTheoremTool',
    'SolveConstraintsTool',
    'SolveLinearOptimizationTool',
    'SimulatePDE1DTool',
    'SimulateStateSpaceTool',
    'RunMonteCarloTool',
]

# Auto-register learning tools on import
try:
    register_learning_tools()
except Exception as e:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Learning tools registration deferred: {e}")

# Auto-register delegation tools. Without this the delegate_task tool exists in
# the tree but is unreachable at runtime -- the same dark-capability pattern as
# create_agents_system and get_upgrade_validator.
try:
    from .delegation_tools import register_delegation_tools
    register_delegation_tools()
except Exception as e:
    import logging
    logging.getLogger(__name__).error(
        f"Delegation tools registration FAILED: {e}", exc_info=True)
