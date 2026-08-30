"""
Core Services Package
Shared services across all TorinAI components
"""

from .unified_llm import UnifiedLLMService, get_llm_service, LLMRequest, LLMResponse

# Health check function for easy access
async def llm_health_check():
    """Get LLM service health status"""
    service = get_llm_service()
    return await service.initialize()

__all__ = [
    'UnifiedLLMService',
    'get_llm_service',
    'LLMRequest',
    'LLMResponse',
    'llm_health_check'
]