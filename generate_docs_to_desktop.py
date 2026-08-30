#!/usr/bin/env python3
"""
Generate Real Documentation with AI - Save to Desktop
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from core.services.unified_llm import get_llm_service
from core.agents.autonomous.general_purpose_executor import GeneralPurposeExecutor
from core.agents.autonomous.shared_types import Task, TaskType, Priority

DESKTOP_PATH = Path.home() / "Desktop" / "TorinAI_Generated_Docs"

async def main():
    print("=" * 80)
    print("GENERATING REAL DOCUMENTATION WITH AI - RESEARCH-FIRST APPROACH")
    print("=" * 80)

    # Create output directory
    DESKTOP_PATH.mkdir(parents=True, exist_ok=True)
    print(f"\n📁 Output directory: {DESKTOP_PATH}\n")

    # Initialize LLM and executor
    print("[SETUP] Loading LLM...")
    llm = get_llm_service()
    await llm.initialize()
    executor = GeneralPurposeExecutor(torin_brain=llm)
    await executor.initialize()
    print("✓ LLM loaded and executor initialized\n")

    # PHASE 1: COMPREHENSIVE RESEARCH
    print("\n" + "="*80)
    print("PHASE 1: RESEARCHING TORINAI CODEBASE")
    print("="*80)

    research_task = Task(
        id="research_torinai",
        type=TaskType.RESEARCH,
        description=f"""Research TorinAI codebase comprehensively. Use memory tools to avoid context limits.

WORKING MEMORY PROTOCOL:
- After EACH discovery: store_memory(content="findings", memory_type="semantic", tags=["research", "category_name"])
- Before new exploration: query_memory(query="what I found", tags=["research"])
- Keep conversation context minimal - discoveries go to memory, not chat history

RESEARCH AREAS (store each to memory with appropriate tags):
1. Project structure → tags: ["research", "structure"]
2. Dependencies & tech specs → tags: ["research", "dependencies"]
3. Tool system (count, categories) → tags: ["research", "tools"]
4. Architecture (agents, services) → tags: ["research", "architecture"]
5. Features & capabilities → tags: ["research", "features"]

CRITICAL FINAL STEP - YOU MUST DO THIS:
1. Query all research: query_memory(tags=["research"])
2. Compile findings into comprehensive report
3. Write complete research to: {DESKTOP_PATH}/research_findings.txt

Include real paths, actual counts, concrete examples - NO fabrication.
DO NOT complete until research_findings.txt is written.""",
        priority=Priority.HIGH
    )

    print("Starting research phase - this may take a few minutes...\n")
    research_result = await executor.execute_task(research_task)
    print(f"✓ Research completed")
    print(f"  Summary: {research_result.get('summary', 'N/A')}\n")

    # Read research findings
    research_file = DESKTOP_PATH / "research_findings.txt"
    if research_file.exists():
        with open(research_file) as f:
            research_data = f.read()
        print(f"✓ Research findings loaded ({len(research_data)} characters)\n")

        # Check if research data is too large (>2000 chars as rough threshold)
        if len(research_data) > 2000:
            print(f"⚠️ Research data is large ({len(research_data)} chars), will use chunking for document generation")
            use_chunking = True

            # Chunk the research data to prevent token overflow
            from core.utils.research_chunker import get_research_chunker
            chunker = get_research_chunker(max_tokens_per_chunk=800)

            # For text-based research, use chunk_text method
            research_chunks = chunker.chunk_text(research_data, overlap_tokens=100)
            print(f"✓ Split research into {len(research_chunks)} chunks\n")
        else:
            use_chunking = False
            research_chunks = [research_data]  # Single chunk
    else:
        print("⚠ Warning: Research findings file not found, proceeding with limited data\n")
        research_data = "Research file not generated properly."
        use_chunking = False
        research_chunks = [research_data]

    # PHASE 2: GENERATE DOCUMENTATION BASED ON RESEARCH
    print("\n" + "="*80)
    print("PHASE 2: GENERATING DOCUMENTATION FROM RESEARCH")
    print("="*80)

    # Prepare research data for prompts (use first chunk or summary if chunked)
    if use_chunking and len(research_chunks) > 0:
        # Use first chunk + indication there's more
        research_for_prompt = research_chunks[0] + f"\n\n[Note: This is chunk 1 of {len(research_chunks)}. Focus on information available in this chunk.]"
        print(f"Using chunk 1/{len(research_chunks)} for document generation ({len(research_for_prompt)} chars)")
    else:
        research_for_prompt = research_data

    docs_to_generate = [
        {
            "name": "PDF System Overview",
            "prompt": f"""Based on the research findings below, use generate_pdf_document to create a comprehensive system overview PDF.

Output path: {DESKTOP_PATH}/TorinAI_Overview.pdf
Title: TorinAI: Autonomous AI System
Author: Dominion Labs

Create well-structured, properly formatted content with markdown formatting:

# Overview
What is TorinAI based on actual codebase

# Architecture
Real architecture from code analysis

# Features
Actual implemented features found in research

# Tool Categories
Real tool breakdown with counts

CRITICAL FORMATTING REQUIREMENTS:
- Use markdown section headers: # for main sections, ## for subsections
- Use bullet points with dashes: - Item text
- Use **bold** for emphasis and component names
- Separate all sections with double newlines (\n\n)
- Format lists properly with one item per line
- DO NOT write section titles inline with content - put headers on their own line

EXAMPLE FORMAT:
# Section Title

Introduction paragraph here.

## Subsection

- **Component Name**: Description here
- **Another Component**: More details

Regular paragraph text here.

Use ONLY information from the research. Do not make up metrics or capabilities.

RESEARCH FINDINGS:
{research_for_prompt}"""
        },
        {
            "name": "PDF Technical Specifications",
            "prompt": f"""Based on the research findings below, use generate_pdf_document to create accurate technical specifications.

Output path: {DESKTOP_PATH}/Technical_Specifications.pdf
Title: TorinAI Technical Specifications
Author: Dominion Labs Engineering

Include ONLY verified information from research:
- Actual Python version from requirements
- Real dependencies (with versions if available)
- Confirmed database type and version
- Storage solutions actually in use
- LLM models actually implemented
- Real system requirements

CRITICAL FORMATTING REQUIREMENTS:
- Use markdown headers: # for main sections, ## for subsections, ### for details
- Use bullet lists with - for all itemized content
- Use **bold** for technical terms and version numbers
- Separate sections with double newlines (\n\n)
- Format code examples with proper indentation
- DO NOT write inline section titles - use proper markdown headers

EXAMPLE FORMAT:
# System Requirements

## Python Environment
- **Python Version**: 3.x (from actual requirements)
- **Package Manager**: pip/conda

## Dependencies
- **Core Libraries**:
  - package-name==version
  - another-package==version

Do not include performance metrics unless found in actual benchmarks/tests.
Do not fabricate or assume any specifications.

RESEARCH FINDINGS:
{research_for_prompt}"""
        },
        {
            "name": "Word API Documentation",
            "prompt": f"""Based on research findings, use generate_word_document to create API documentation.

Output path: {DESKTOP_PATH}/API_Documentation.docx
Title: TorinAI API Documentation
Author: Dominion Labs

Document actual API modules found in research:
- Core services and their methods
- Tool registry structure
- Agent interfaces
- Include real code examples if found

RESEARCH FINDINGS:
{research_for_prompt}"""
        },
        {
            "name": "Architecture Diagram",
            "prompt": f"""Based on research findings, use generate_architecture_diagram to create a high-quality system architecture diagram.

Output path: {DESKTOP_PATH}/system_architecture.png
Title: TorinAI System Architecture
Style: layered

CRITICAL FORMATTING REQUIREMENTS:
- Use LARGE font sizes (minimum 14pt for text)
- Add generous spacing between all components (minimum 50px padding)
- Ensure NO overlapping text or arrows
- Use clear, professional colors with good contrast
- Make the diagram wide enough to prevent crowding
- Use proper alignment and symmetry

Use ONLY actual components discovered in research - do not fabricate.

RESEARCH FINDINGS:
{research_for_prompt}"""
        },
        {
            "name": "PowerPoint Presentation",
            "prompt": f"""Based on research findings, use generate_powerpoint to create a presentation.

Output path: {DESKTOP_PATH}/TorinAI_Presentation.pptx
Title: TorinAI Overview
Author: Dominion Labs

Create slides with actual information from research (not generic fluff):
- Slide 1: Introduction with real facts
- Slide 2: Core features actually implemented
- Slide 3: Architecture with real components
- Slide 4: Tool categories with real counts

RESEARCH FINDINGS:
{research_for_prompt}"""
        },
        {
            "name": "Word User Guide",
            "prompt": f"""Based on research findings, use generate_word_document to create a comprehensive, practical user guide.

Output path: {DESKTOP_PATH}/User_Guide.docx
Title: TorinAI User Guide
Author: Dominion Labs Support

Create detailed sections based on what's actually in the codebase:
1. Getting Started
   - Real installation steps with actual commands
   - Prerequisites based on actual requirements
   - Configuration setup from actual config files

2. Basic Usage
   - Concrete usage examples from code/tests
   - Real command-line interfaces discovered
   - Actual API calls with examples

3. Advanced Features
   - Real advanced features found in codebase
   - Actual configuration options
   - Integration examples if found

4. Troubleshooting
   - Common errors from actual error handling code
   - Real solutions based on code analysis
   - Debug tips from actual logging/debug code

CRITICAL REQUIREMENTS:
- Include REAL code examples, not placeholders
- Use ACTUAL file paths and commands discovered
- Provide CONCRETE steps, not vague instructions
- Include real configuration values and options
- Make it immediately actionable for users

Do not include generic advice or placeholder content.

RESEARCH FINDINGS:
{research_for_prompt}"""
        },
    ]

    for idx, doc in enumerate(docs_to_generate, 1):
        print(f"\n{'='*80}")
        print(f"[{idx}/{len(docs_to_generate)}] Generating: {doc['name']}")
        print(f"{'='*80}")

        task = Task(
            id=f"gen_doc_{idx}",
            type=TaskType.EXECUTION,
            description=doc['prompt'],
            priority=Priority.HIGH
        )

        try:
            # Use executor's task execution which now includes memory capture
            result = await executor.execute_task(task)
            print(f"✓ {doc['name']} generated (captured in memory)")
            print(f"  Summary: {result.get('summary', 'N/A')}")
            print(f"  Success: {result.get('success', False)}")
        except Exception as e:
            print(f"✗ Failed to generate {doc['name']}: {e}")

    # Cleanup
    if llm and hasattr(llm, 'shutdown'):
        await llm.shutdown()

    print(f"\n{'='*80}")
    print(f"✓ Documentation generated in: {DESKTOP_PATH}")
    print(f"{'='*80}")

if __name__ == "__main__":
    asyncio.run(main())
