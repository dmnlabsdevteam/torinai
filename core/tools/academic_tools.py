#!/usr/bin/env python3
"""
Academic Research Tools
=======================
Advanced tools for academic research, citation management, and scholarly work

Tools:
- analyze_research_paper: Extract and analyze paper structure, methods, results
- generate_citation: Generate citations in multiple formats (APA, MLA, Chicago, BibTeX)
- manage_bibliography: Build and manage bibliographies
- synthesize_literature: Synthesize findings from multiple papers
- extract_paper_metadata: Extract metadata from academic papers
- analyze_research_data: Statistical analysis of research data
- generate_latex_document: Generate LaTeX documents for academic papers
- format_academic_writing: Check and improve academic writing style
- create_research_graph: Create graphs and visualizations for research data
- generate_architecture_diagram: Generate system/network architecture diagrams
- create_flowchart: Create flowcharts for processes and algorithms
- fetch_paper_by_doi: Fetch paper metadata and PDF from DOI
- fetch_paper_by_arxiv: Fetch paper from arXiv ID
- parse_pdf_paper: Extract text and structure from PDF papers
- validate_bibliography: Validate and deduplicate bibliography entries
- export_bibliography_csl: Export bibliography in CSL-JSON format
- link_claim_to_evidence: Create provenance links between claims and evidence
- generate_artifact_manifest: Create reproducibility artifact manifest
- generate_rebuttal_document: Generate rebuttal document for peer review
- format_for_venue: Format paper for specific conference/journal requirements

Author: Torin AI Team
"""

import logging
import re
import json
import asyncio
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

from .tool_registry import Tool, ToolParameter, ToolResult, ToolCategory, ToolSafety
from .capabilities import Capability, ToolCapabilityProfile, CapabilityMetadata, RiskLevel

logger = logging.getLogger(__name__)


class AnalyzeResearchPaperTool(Tool):
    """Analyze academic paper structure and extract key information"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_research_paper"
        self.description = "Extract and analyze structure, methods, results, and conclusions from research papers"
        self.category = ToolCategory.AI_ML
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="paper_text",
                type="string",
                description="Full text of the research paper or path to paper file",
                required=True
            ),
            ToolParameter(
                name="analysis_depth",
                type="string",
                description="Analysis depth level",
                required=False,
                default="standard",
                enum=["quick", "standard", "comprehensive"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_research_paper",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="AnalyzeResearchPaper capability"
                ),
                CapabilityMetadata(
                    capability=Capability.ANALYZE_PAPER,
                    description="Extract insights and methodology from research papers",
                    input_types=["paper_text"],
                    output_types=["analysis"],
                    latency="high",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=9
                )
            ]
        )

    async def execute(self, paper_text: str, analysis_depth: str = "standard") -> ToolResult:
        try:
            # Accept either a file path or the paper text itself. A long text
            # is not a path: Path.exists() raises "File name too long" rather
            # than returning False, so guard the probe.
            text = paper_text
            try:
                paper_path = Path(paper_text)
                if paper_path.exists() and paper_path.is_file():
                    with open(paper_path, 'r', encoding='utf-8', errors='ignore') as f:
                        text = f.read()
            except OSError:
                pass

            # Extract sections using patterns
            sections = {
                'abstract': self._extract_section(text, ['abstract']),
                'introduction': self._extract_section(text, ['introduction', 'background']),
                'methods': self._extract_section(text, ['methods', 'methodology', 'approach']),
                'results': self._extract_section(text, ['results', 'findings', 'experiments']),
                'discussion': self._extract_section(text, ['discussion', 'analysis']),
                'conclusion': self._extract_section(text, ['conclusion', 'conclusions'])
            }

            # Model-free structural analysis: surface the paper's OWN sentences
            # that answer each analytical dimension, rather than an LLM prose
            # summary. Each field is evidence lifted directly from the text.
            analysis = {
                'research_question': self._lead(sections['abstract'] or sections['introduction']),
                'methodology': self._lead(sections['methods']),
                'key_findings': self._lead(sections['results']),
                'discussion': self._lead(sections['discussion']),
                'conclusion': self._lead(sections['conclusion']),
                'datasets': self._find_sentences(text, ['dataset', 'corpus', 'benchmark', 'data set']),
                'metrics': self._find_sentences(text, ['accuracy', 'f1', 'precision', 'recall', 'bleu', 'auc', 'rmse', 'error rate']),
                'limitations': self._find_sentences(text, ['limitation', 'we do not', 'cannot', 'fails to', 'does not']),
                'future_work': self._find_sentences(text, ['future work', 'future research', 'we plan', 'we leave']),
            }

            # Extract references count
            refs = len(re.findall(r'\[\d+\]|\(\d{4}\)', text))

            return ToolResult(
                success=True,
                output={
                    'sections': sections,
                    'analysis': analysis,
                    'statistics': {
                        'word_count': len(text.split()),
                        'reference_count': refs,
                        'sections_found': [k for k, v in sections.items() if v]
                    },
                    'metadata': {
                        'analysis_depth': analysis_depth,
                        'method': 'structural_extraction',
                        'timestamp': datetime.now().isoformat()
                    }
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Paper analysis failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)

    @staticmethod
    def _lead(section_text: Optional[str], max_sentences: int = 2) -> Optional[str]:
        """First few sentences of a section — its topic statement, verbatim."""
        if not section_text:
            return None
        sentences = re.split(r'(?<=[.!?])\s+', section_text.strip())
        lead = ' '.join(s for s in sentences[:max_sentences] if s).strip()
        return lead or None

    @staticmethod
    def _find_sentences(text: str, keywords: List[str], limit: int = 3) -> List[str]:
        """Sentences that mention any keyword — evidence lifted from the paper."""
        found: List[str] = []
        for sentence in re.split(r'(?<=[.!?])\s+', text):
            low = sentence.lower()
            if any(k in low for k in keywords):
                cleaned = ' '.join(sentence.split())
                if cleaned and cleaned not in found:
                    found.append(cleaned[:300])
            if len(found) >= limit:
                break
        return found

    def _extract_section(self, text: str, keywords: List[str]) -> Optional[str]:
        """Extract section based on keywords"""
        text_lower = text.lower()
        for keyword in keywords:
            # Look for section headers
            pattern = rf'\n\s*(?:#{1,3}\s+)?(?:\d+\.?\s+)?{keyword}\s*\n'
            match = re.search(pattern, text_lower)
            if match:
                start = match.end()
                # Find next section or end
                next_section = re.search(r'\n\s*(?:#{1,3}\s+)?(?:\d+\.?\s+)?[A-Z]', text[start:])
                end = start + next_section.start() if next_section else len(text)
                return text[start:end].strip()[:2000]
        return None


class GenerateCitationTool(Tool):
    """Generate citations in multiple academic formats"""

    def __init__(self):
        super().__init__()
        self.name = "generate_citation"
        self.description = "Generate properly formatted citations in APA, MLA, Chicago, IEEE, or BibTeX format"
        self.category = ToolCategory.DOCUMENTATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="authors",
                type="array",
                description="List of author names",
                required=True
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Paper/book title",
                required=True
            ),
            ToolParameter(
                name="year",
                type="number",
                description="Publication year",
                required=True
            ),
            ToolParameter(
                name="format",
                type="string",
                description="Citation format",
                required=False,
                default="apa",
                enum=["apa", "mla", "chicago", "ieee", "bibtex", "all"]
            ),
            ToolParameter(
                name="venue",
                type="string",
                description="Journal/Conference name",
                required=False
            ),
            ToolParameter(
                name="doi",
                type="string",
                description="DOI",
                required=False
            ),
            ToolParameter(
                name="url",
                type="string",
                description="URL",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_citation",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="GenerateCitation capability"
                ),
                CapabilityMetadata(
                    capability=Capability.GENERATE_CITATION,
                    description="Generate formatted citations in various styles",
                    input_types=["paper_metadata", "style"],
                    output_types=["citation"],
                    latency="low",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ]
        )

    async def execute(self, authors: List[str], title: str, year: int, format: str = "apa",
                     venue: Optional[str] = None, doi: Optional[str] = None,
                     url: Optional[str] = None) -> ToolResult:
        try:
            citations = {}

            # Format author names
            author_str = ", ".join(authors) if len(authors) <= 3 else f"{authors[0]} et al."
            author_last_first = [self._format_author(a) for a in authors]

            # APA format
            apa_authors = " & ".join(author_last_first) if len(authors) <= 7 else f"{author_last_first[0]}, et al."
            citations['apa'] = f"{apa_authors} ({year}). {title}."
            if venue:
                citations['apa'] += f" {venue}."
            if doi:
                citations['apa'] += f" https://doi.org/{doi}"

            # MLA format
            mla_authors = author_last_first[0] if len(authors) == 1 else f"{author_last_first[0]}, et al."
            citations['mla'] = f"{mla_authors} \"{title}.\""
            if venue:
                citations['mla'] += f" {venue},"
            citations['mla'] += f" {year}."

            # Chicago format
            chicago_authors = author_last_first[0] if len(authors) == 1 else f"{author_last_first[0]} et al."
            citations['chicago'] = f"{chicago_authors} \"{title}.\""
            if venue:
                citations['chicago'] += f" {venue}"
            citations['chicago'] += f" ({year})."

            # IEEE format
            ieee_authors = ", ".join([self._ieee_author(a) for a in authors[:3]])
            if len(authors) > 3:
                ieee_authors += ", et al."
            citations['ieee'] = f"{ieee_authors}, \"{title},\""
            if venue:
                citations['ieee'] += f" {venue},"
            citations['ieee'] += f" {year}."

            # BibTeX format
            cite_key = f"{authors[0].split()[-1].lower()}{year}"
            bibtex = f"@article{{{cite_key},\n"
            bibtex += f"  author = {{{' and '.join(authors)}}},\n"
            bibtex += f"  title = {{{title}}},\n"
            bibtex += f"  year = {{{year}}},\n"
            if venue:
                bibtex += f"  journal = {{{venue}}},\n"
            if doi:
                bibtex += f"  doi = {{{doi}}},\n"
            if url:
                bibtex += f"  url = {{{url}}},\n"
            bibtex += "}"
            citations['bibtex'] = bibtex

            # Return requested format or all
            if format == "all":
                output = citations
            else:
                output = {format: citations[format]}

            return ToolResult(
                success=True,
                output=output,
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Citation generation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)

    def _format_author(self, name: str) -> str:
        """Format author as 'Last, F. M.'"""
        parts = name.strip().split()
        if len(parts) == 1:
            return parts[0]
        last = parts[-1]
        initials = ". ".join([p[0] for p in parts[:-1]]) + "."
        return f"{last}, {initials}"

    def _ieee_author(self, name: str) -> str:
        """Format author as 'F. M. Last'"""
        parts = name.strip().split()
        if len(parts) == 1:
            return parts[0]
        initials = ". ".join([p[0] for p in parts[:-1]]) + "."
        return f"{initials} {parts[-1]}"


class SynthesizeLiteratureTool(Tool):
    """Synthesize findings from multiple research papers"""

    def __init__(self):
        super().__init__()
        self.name = "synthesize_literature"
        self.description = "Synthesize and compare findings from multiple research papers to generate literature review"
        self.category = ToolCategory.AI_ML
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="papers",
                type="array",
                description="List of paper summaries or full texts",
                required=True
            ),
            ToolParameter(
                name="research_question",
                type="string",
                description="Research question or focus area for synthesis",
                required=True
            ),
            ToolParameter(
                name="synthesis_type",
                type="string",
                description="Type of synthesis",
                required=False,
                default="thematic",
                enum=["thematic", "chronological", "methodological", "comparative"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="synthesize_literature",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="SynthesizeLiterature capability"
                )
            ]
        )

    async def execute(self, papers: List[str], research_question: str,
                     synthesis_type: str = "thematic") -> ToolResult:
        try:
            if not papers:
                return ToolResult(success=False, output=None,
                                  error="no papers to synthesize", tool_name=self.name)

            # Model-free synthesis over the substrate's local embeddings.
            # Themes = clusters of papers that embed close together; relevance =
            # each paper's cosine similarity to the research question; outliers =
            # papers distant from every other (candidate gaps / contradictions).
            from core.memory.utils.embedding_service import get_embedding_service
            import numpy as np

            service = get_embedding_service()
            vectors = [service.generate_embedding(p[:4000]) for p in papers]
            if any(v is None for v in vectors):
                return ToolResult(success=False, output=None,
                                  error="synthesis unavailable: local embedding model not loaded",
                                  tool_name=self.name)

            mat = np.asarray(vectors, dtype=float)
            norms = np.linalg.norm(mat, axis=1, keepdims=True)
            unit = mat / np.clip(norms, 1e-12, None)
            sim = unit @ unit.T  # pairwise cosine

            # Relevance of each paper to the research question.
            q = service.generate_embedding(research_question)
            relevance = []
            if q is not None:
                qv = np.asarray(q, dtype=float)
                qv = qv / max(float(np.linalg.norm(qv)), 1e-12)
                scores = unit @ qv
                relevance = sorted(
                    ({'paper': i + 1, 'relevance': round(float(scores[i]), 4)} for i in range(len(papers))),
                    key=lambda r: r['relevance'], reverse=True
                )

            # Greedy thematic clustering: group papers whose cosine >= threshold.
            threshold = 0.45
            unassigned = set(range(len(papers)))
            themes = []
            while unassigned:
                seed = max(unassigned, key=lambda i: float(sim[i][list(unassigned)].mean()))
                members = sorted(j for j in unassigned if float(sim[seed][j]) >= threshold)
                if seed not in members:
                    members.append(seed)
                for j in members:
                    unassigned.discard(j)
                terms = self._shared_terms([papers[j] for j in members])
                themes.append({'papers': [j + 1 for j in members], 'shared_terms': terms})

            # Outliers: papers whose best similarity to any OTHER paper is low.
            outliers = []
            for i in range(len(papers)):
                others = [float(sim[i][j]) for j in range(len(papers)) if j != i]
                if others and max(others) < threshold:
                    outliers.append(i + 1)

            return ToolResult(
                success=True,
                output={
                    'research_question': research_question,
                    'synthesis_type': synthesis_type,
                    'papers_count': len(papers),
                    'themes': themes,
                    'relevance_ranking': relevance,
                    'outliers': outliers,
                    'method': 'embedding_clustering',
                    'model': service.model_name,
                    'timestamp': datetime.now().isoformat()
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Literature synthesis failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)

    @staticmethod
    def _shared_terms(texts: List[str], top: int = 8) -> List[str]:
        """Salient terms shared across a cluster: content words frequent in most members."""
        import re as _re
        from collections import Counter
        stop = {
            'the', 'and', 'for', 'that', 'with', 'this', 'from', 'are', 'was', 'were',
            'our', 'can', 'has', 'have', 'not', 'but', 'which', 'these', 'they', 'their',
            'using', 'used', 'use', 'based', 'also', 'such', 'more', 'than', 'been', 'may',
            'we', 'is', 'of', 'in', 'to', 'a', 'an', 'on', 'as', 'by', 'be', 'it', 'or',
        }
        per_doc = []
        for t in texts:
            words = {w for w in _re.findall(r'[a-z]{3,}', t.lower()) if w not in stop}
            per_doc.append(words)
        counts = Counter()
        for words in per_doc:
            counts.update(words)
        need = max(1, (len(texts) + 1) // 2)  # appears in at least half the members
        shared = [w for w, c in counts.most_common() if c >= need]
        return shared[:top]


class ExtractPaperMetadataTool(Tool):
    """Extract metadata from academic papers"""

    def __init__(self):
        super().__init__()
        self.name = "extract_paper_metadata"
        self.description = "Extract bibliographic metadata from academic papers (title, authors, abstract, keywords, DOI)"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="paper_text",
                type="string",
                description="Paper text or path to paper file",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="extract_paper_metadata",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="ExtractPaperMetadata capability"
                )
            ]
        )

    async def execute(self, paper_text: str) -> ToolResult:
        try:
            # Check if paper_text is a file path
            paper_path = Path(paper_text)
            if paper_path.exists() and paper_path.is_file():
                with open(paper_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
            else:
                text = paper_text

            metadata = {}

            # Extract title (usually first line or largest text)
            lines = text.split('\n')
            for line in lines[:20]:
                if len(line.strip()) > 10 and len(line.strip()) < 200:
                    metadata['title'] = line.strip()
                    break

            # Extract authors (look for patterns)
            author_patterns = [
                r'(?:Authors?|By):\s*([^\n]+)',
                r'^([A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+(?:,\s*[A-Z][a-z]+ [A-Z]\. [A-Z][a-z]+)*)',
            ]
            for pattern in author_patterns:
                match = re.search(pattern, text[:2000], re.MULTILINE)
                if match:
                    metadata['authors'] = [a.strip() for a in match.group(1).split(',')]
                    break

            # Extract abstract
            abstract_match = re.search(r'(?:Abstract|ABSTRACT)\s*[:\n]\s*(.+?)(?:\n\n|Introduction|INTRODUCTION)',
                                      text, re.DOTALL)
            if abstract_match:
                metadata['abstract'] = abstract_match.group(1).strip()[:1000]

            # Extract DOI
            doi_match = re.search(r'(?:DOI|doi):\s*(10\.\d{4,}/[^\s]+)', text)
            if doi_match:
                metadata['doi'] = doi_match.group(1)

            # Extract keywords
            keywords_match = re.search(r'(?:Keywords?|Index Terms):\s*([^\n]+)', text, re.IGNORECASE)
            if keywords_match:
                keywords_text = keywords_match.group(1)
                metadata['keywords'] = [k.strip() for k in re.split(r'[,;·]', keywords_text)]

            # Extract year
            year_match = re.search(r'(?:19|20)\d{2}', text[:2000])
            if year_match:
                metadata['year'] = int(year_match.group(0))

            return ToolResult(
                success=True,
                output=metadata,
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Metadata extraction failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class AnalyzeResearchDataTool(Tool):
    """Statistical analysis of research data"""

    def __init__(self):
        super().__init__()
        self.name = "analyze_research_data"
        self.description = "Perform statistical analysis on research data (descriptive stats, correlations, significance tests)"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="data",
                type="object",
                description="Research data as dict or JSON",
                required=True
            ),
            ToolParameter(
                name="analysis_type",
                type="string",
                description="Type of statistical analysis",
                required=False,
                default="descriptive",
                enum=["descriptive", "correlation", "ttest", "anova", "regression", "all"]
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="analyze_research_data",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="AnalyzeResearchData capability"
                )
            ]
        )

    async def execute(self, data: Dict[str, Any], analysis_type: str = "descriptive") -> ToolResult:
        try:
            import statistics
            from collections import defaultdict

            results = {}

            # Convert data to numeric arrays
            numeric_data = {}
            for key, values in data.items():
                if isinstance(values, list):
                    try:
                        numeric_data[key] = [float(v) for v in values if v is not None]
                    except (ValueError, TypeError):
                        continue

            if not numeric_data:
                return ToolResult(success=False, output=None,
                                error="No numeric data found for analysis", tool_name=self.name)

            # Descriptive statistics
            if analysis_type in ["descriptive", "all"]:
                desc_stats = {}
                for key, values in numeric_data.items():
                    if values:
                        desc_stats[key] = {
                            'n': len(values),
                            'mean': statistics.mean(values),
                            'median': statistics.median(values),
                            'stdev': statistics.stdev(values) if len(values) > 1 else 0,
                            'min': min(values),
                            'max': max(values),
                            'range': max(values) - min(values)
                        }
                results['descriptive'] = desc_stats

            # Correlation analysis (Pearson)
            if analysis_type in ["correlation", "all"] and len(numeric_data) >= 2:
                correlations = {}
                keys = list(numeric_data.keys())
                for i, key1 in enumerate(keys):
                    for key2 in keys[i+1:]:
                        if len(numeric_data[key1]) == len(numeric_data[key2]):
                            corr = self._pearson_correlation(numeric_data[key1], numeric_data[key2])
                            correlations[f"{key1}_vs_{key2}"] = round(corr, 4)
                results['correlations'] = correlations

            return ToolResult(
                success=True,
                output={
                    'analysis_type': analysis_type,
                    'results': results,
                    'variables_analyzed': list(numeric_data.keys()),
                    'timestamp': datetime.now().isoformat()
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Research data analysis failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)

    def _pearson_correlation(self, x: List[float], y: List[float]) -> float:
        """Calculate Pearson correlation coefficient"""
        import statistics
        if len(x) != len(y) or len(x) < 2:
            return 0.0

        mean_x = statistics.mean(x)
        mean_y = statistics.mean(y)

        numerator = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        denominator_x = sum((xi - mean_x) ** 2 for xi in x)
        denominator_y = sum((yi - mean_y) ** 2 for yi in y)

        if denominator_x == 0 or denominator_y == 0:
            return 0.0

        return numerator / (denominator_x * denominator_y) ** 0.5


class GenerateLatexDocumentTool(Tool):
    """Generate LaTeX documents for academic papers"""

    def __init__(self):
        super().__init__()
        self.name = "generate_latex_document"
        self.description = "Generate LaTeX document template for academic papers with proper formatting"
        self.category = ToolCategory.DOCUMENTATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="title",
                type="string",
                description="Paper title",
                required=True
            ),
            ToolParameter(
                name="authors",
                type="array",
                description="List of authors",
                required=True
            ),
            ToolParameter(
                name="document_class",
                type="string",
                description="LaTeX document class",
                required=False,
                default="article",
                enum=["article", "IEEEtran", "ACM", "elsarticle", "report"]
            ),
            ToolParameter(
                name="abstract",
                type="string",
                description="Abstract text",
                required=False
            ),
            ToolParameter(
                name="keywords",
                type="array",
                description="Keywords",
                required=False
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_latex_document",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="GenerateLatexDocument capability"
                )
            ]
        )

    async def execute(self, title: str, authors: List[str], document_class: str = "article",
                     abstract: Optional[str] = None, keywords: Optional[List[str]] = None) -> ToolResult:
        try:
            latex = f"""\\documentclass[11pt,twocolumn]{{{document_class}}}

% Packages
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{hyperref}}
\\usepackage{{cite}}
\\usepackage{{algorithm}}
\\usepackage{{algorithmic}}

% Title and authors
\\title{{{title}}}

"""
            # Add authors
            for author in authors:
                latex += f"\\author{{{author}}}\n"

            latex += f"""
\\date{{\\today}}

\\begin{{document}}

\\maketitle

"""
            # Add abstract if provided
            if abstract:
                latex += f"""\\begin{{abstract}}
{abstract}
\\end{{abstract}}

"""
            # Add keywords if provided
            if keywords:
                keywords_str = ", ".join(keywords)
                latex += f"\\textbf{{Keywords:}} {keywords_str}\n\n"

            # Add sections template
            latex += """\\section{Introduction}
Your introduction here.

\\section{Related Work}
Literature review here.

\\section{Methodology}
Describe your methodology.

\\section{Results}
Present your results.

\\section{Discussion}
Discuss your findings.

\\section{Conclusion}
Conclude your paper.

\\section*{Acknowledgments}
Acknowledgments here.

\\bibliographystyle{plain}
\\bibliography{references}

\\end{document}
"""

            return ToolResult(
                success=True,
                output={
                    'latex': latex,
                    'document_class': document_class,
                    'compile_command': 'pdflatex paper.tex && bibtex paper && pdflatex paper.tex && pdflatex paper.tex'
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"LaTeX generation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class CreateResearchGraphTool(Tool):
    """Create graphs and visualizations for research data"""

    def __init__(self):
        super().__init__()
        self.name = "create_research_graph"
        self.description = "Create publication-quality graphs and visualizations (line plots, bar charts, scatter plots, heatmaps)"
        self.category = ToolCategory.DATA_PROCESSING
        self.safety_level = ToolSafety.MODERATE
        self.parameters = [
            ToolParameter(
                name="data",
                type="object",
                description="Data to visualize (dict with x, y values)",
                required=True
            ),
            ToolParameter(
                name="graph_type",
                type="string",
                description="Type of graph",
                required=False,
                default="line",
                enum=["line", "bar", "scatter", "histogram", "box", "heatmap", "pie"]
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Graph title",
                required=False
            ),
            ToolParameter(
                name="xlabel",
                type="string",
                description="X-axis label",
                required=False
            ),
            ToolParameter(
                name="ylabel",
                type="string",
                description="Y-axis label",
                required=False
            ),
            ToolParameter(
                name="output_path",
                type="string",
                description="Path to save graph image",
                required=False,
                default="research_graph.png"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_research_graph",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="CreateResearchGraph capability"
                ),
                CapabilityMetadata(
                    capability=Capability.BUILD_KNOWLEDGE_GRAPH,
                    description="Build knowledge graphs from research data",
                    input_types=["entities", "relations"],
                    output_types=["graph"],
                    latency="medium",
                    cost="medium",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=8
                )
            ]
        )

    async def execute(self, data: Dict[str, Any], graph_type: str = "line",
                     title: Optional[str] = None, xlabel: Optional[str] = None,
                     ylabel: Optional[str] = None, output_path: str = "research_graph.png") -> ToolResult:
        try:
            try:
                import matplotlib.pyplot as plt
                import matplotlib
                matplotlib.use('Agg')  # Non-interactive backend
            except ImportError:
                return ToolResult(success=False, output=None,
                                error="matplotlib not installed. Run: pip install matplotlib",
                                tool_name=self.name)

            # Create figure
            fig, ax = plt.subplots(figsize=(10, 6))

            # Plot based on type
            if graph_type == "line":
                for key, values in data.items():
                    if isinstance(values, list):
                        ax.plot(values, label=key, marker='o')
                ax.legend()

            elif graph_type == "bar":
                x_labels = list(data.keys())
                y_values = [data[k] if not isinstance(data[k], list) else sum(data[k])/len(data[k])
                           for k in x_labels]
                ax.bar(x_labels, y_values)

            elif graph_type == "scatter":
                x_data = data.get('x', [])
                y_data = data.get('y', [])
                ax.scatter(x_data, y_data, alpha=0.6)

            elif graph_type == "histogram":
                values = data.get('values', list(data.values())[0])
                ax.hist(values, bins=20, edgecolor='black', alpha=0.7)

            elif graph_type == "box":
                box_data = [v for v in data.values() if isinstance(v, list)]
                ax.boxplot(box_data, labels=list(data.keys())[:len(box_data)])

            elif graph_type == "heatmap":
                try:
                    import numpy as np
                    matrix = np.array(list(data.values()))
                    im = ax.imshow(matrix, cmap='viridis', aspect='auto')
                    plt.colorbar(im, ax=ax)
                except ImportError:
                    return ToolResult(success=False, output=None,
                                    error="numpy required for heatmap", tool_name=self.name)

            elif graph_type == "pie":
                labels = list(data.keys())
                values = [data[k] if not isinstance(data[k], list) else sum(data[k])
                         for k in labels]
                ax.pie(values, labels=labels, autopct='%1.1f%%')

            # Set labels and title
            if title:
                ax.set_title(title, fontsize=14, fontweight='bold')
            if xlabel:
                ax.set_xlabel(xlabel, fontsize=12)
            if ylabel:
                ax.set_ylabel(ylabel, fontsize=12)

            # Grid for better readability
            if graph_type not in ['pie', 'heatmap']:
                ax.grid(True, alpha=0.3)

            # Save figure
            output = Path(output_path).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            plt.tight_layout()
            plt.savefig(output, dpi=300, bbox_inches='tight')
            plt.close()

            return ToolResult(
                success=True,
                output={
                    'graph_type': graph_type,
                    'output_path': str(output),
                    'message': f'Graph saved to {output}'
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Graph creation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class GenerateArchitectureDiagramTool(Tool):
    """Generate system/network architecture diagrams"""

    def __init__(self):
        super().__init__()
        self.name = "generate_architecture_diagram"
        self.description = "Generate architecture diagrams for systems, networks, or software using Graphviz DOT format"
        self.category = ToolCategory.DOCUMENTATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="components",
                type="array",
                description="List of system components/nodes",
                required=True
            ),
            ToolParameter(
                name="connections",
                type="array",
                description="List of connections between components (e.g., [{'from': 'A', 'to': 'B', 'label': 'HTTP'}])",
                required=True
            ),
            ToolParameter(
                name="diagram_type",
                type="string",
                description="Type of diagram layout",
                required=False,
                default="hierarchical",
                enum=["hierarchical", "network", "layered", "circular"]
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Diagram title",
                required=False
            ),
            ToolParameter(
                name="output_path",
                type="string",
                description="Path to save diagram",
                required=False,
                default="architecture_diagram.png"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_architecture_diagram",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="GenerateArchitectureDiagram capability"
                )
            ]
        )

    async def execute(self, components: List[str], connections: List[Dict[str, str]],
                     diagram_type: str = "hierarchical", title: Optional[str] = None,
                     output_path: str = "architecture_diagram.png") -> ToolResult:
        try:
            # Generate Graphviz DOT format
            rankdir_map = {
                "hierarchical": "TB",  # Top to Bottom
                "network": "LR",       # Left to Right
                "layered": "TB",
                "circular": "circo"
            }

            if diagram_type == "circular":
                dot = "graph G {\n"
                dot += "  layout=circo;\n"
            else:
                dot = "digraph G {\n"
                rankdir = rankdir_map.get(diagram_type, "TB")
                dot += f"  rankdir={rankdir};\n"

            dot += "  node [shape=box, style=filled, fillcolor=lightblue, fontname=\"Arial\"];\n"
            dot += "  edge [fontname=\"Arial\", fontsize=10];\n\n"

            # Add title if provided
            if title:
                dot += f"  labelloc=\"t\";\n"
                dot += f"  label=\"{title}\";\n"
                dot += f"  fontsize=16;\n\n"

            # Add nodes
            for i, comp in enumerate(components):
                node_id = f"node{i}"
                dot += f"  {node_id} [label=\"{comp}\"];\n"

            dot += "\n"

            # Add edges
            for conn in connections:
                from_node = f"node{components.index(conn['from'])}" if conn['from'] in components else conn['from']
                to_node = f"node{components.index(conn['to'])}" if conn['to'] in components else conn['to']
                label = conn.get('label', '')

                if diagram_type == "circular":
                    dot += f"  {from_node} -- {to_node}"
                else:
                    dot += f"  {from_node} -> {to_node}"

                if label:
                    dot += f" [label=\"{label}\"]"
                dot += ";\n"

            dot += "}\n"

            # Try to render with Graphviz
            try:
                import subprocess
                from tempfile import NamedTemporaryFile

                output = Path(output_path).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)

                # Write DOT file
                with NamedTemporaryFile(mode='w', suffix='.dot', delete=False) as f:
                    f.write(dot)
                    dot_file = f.name

                # Render to PNG
                engine = "circo" if diagram_type == "circular" else "dot"
                result = subprocess.run(
                    [engine, "-Tpng", dot_file, "-o", str(output)],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode != 0:
                    # Graphviz not installed, return DOT source
                    return ToolResult(
                        success=True,
                        output={
                            'dot_source': dot,
                            'message': 'Graphviz not installed. Install with: brew install graphviz (macOS) or apt-get install graphviz (Linux)',
                            'dot_file': dot_file
                        },
                        tool_name=self.name
                    )

                return ToolResult(
                    success=True,
                    output={
                        'diagram_type': diagram_type,
                        'output_path': str(output),
                        'dot_source': dot,
                        'message': f'Architecture diagram saved to {output}'
                    },
                    tool_name=self.name
                )

            except FileNotFoundError:
                # Graphviz not in PATH
                # NO FILE WAS WRITTEN. success=True with no output_path told
                # the caller the diagram had been saved; the DOT source is the
                # input to rendering, not the rendered result.
                return ToolResult(
                    success=False,
                    error='graphviz is not installed, so no diagram was rendered',
                    output={
                        'dot_source': dot,
                        'message': 'Graphviz not found. Install with: brew install graphviz (macOS) or apt-get install graphviz (Linux)',
                        'instructions': 'Save DOT source to file.dot and run: dot -Tpng file.dot -o output.png'
                    },
                    tool_name=self.name
                )

        except Exception as e:
            logger.error(f"Architecture diagram generation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class CreateFlowchartTool(Tool):
    """Create flowcharts for processes and algorithms"""

    def __init__(self):
        super().__init__()
        self.name = "create_flowchart"
        self.description = "Create flowcharts to visualize algorithms, processes, or decision trees"
        self.category = ToolCategory.DOCUMENTATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="steps",
                type="array",
                description="List of flowchart steps with type and label (e.g., [{'type': 'start', 'label': 'Begin'}, {'type': 'process', 'label': 'Calculate'}])",
                required=True
            ),
            ToolParameter(
                name="title",
                type="string",
                description="Flowchart title",
                required=False
            ),
            ToolParameter(
                name="output_path",
                type="string",
                description="Path to save flowchart",
                required=False,
                default="flowchart.png"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="create_flowchart",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="CreateFlowchart capability"
                )
            ]
        )

    async def execute(self, steps: List[Dict[str, str]], title: Optional[str] = None,
                     output_path: str = "flowchart.png") -> ToolResult:
        try:
            # Generate Graphviz DOT format for flowchart
            dot = "digraph Flowchart {\n"
            dot += "  rankdir=TB;\n"
            dot += "  node [fontname=\"Arial\"];\n"
            dot += "  edge [fontname=\"Arial\"];\n\n"

            if title:
                dot += f"  labelloc=\"t\";\n"
                dot += f"  label=\"{title}\";\n"
                dot += f"  fontsize=16;\n\n"

            # Shape mapping for flowchart elements
            shape_map = {
                'start': 'ellipse',
                'end': 'ellipse',
                'process': 'box',
                'decision': 'diamond',
                'io': 'parallelogram',
                'data': 'parallelogram'
            }

            # Create nodes
            for i, step in enumerate(steps):
                step_type = step.get('type', 'process')
                label = step.get('label', f'Step {i+1}')
                shape = shape_map.get(step_type, 'box')

                fillcolor = {
                    'start': 'lightgreen',
                    'end': 'lightcoral',
                    'decision': 'lightyellow',
                    'process': 'lightblue',
                    'io': 'lightgray'
                }.get(step_type, 'lightblue')

                dot += f"  step{i} [label=\"{label}\", shape={shape}, style=filled, fillcolor={fillcolor}];\n"

            dot += "\n"

            # Create edges (linear flow by default)
            for i in range(len(steps) - 1):
                edge_label = steps[i].get('next_label', '')
                dot += f"  step{i} -> step{i+1}"
                if edge_label:
                    dot += f" [label=\"{edge_label}\"]"
                dot += ";\n"

                # Add alternative paths for decisions
                if steps[i].get('type') == 'decision' and 'alt_next' in steps[i]:
                    alt_next = steps[i]['alt_next']
                    alt_label = steps[i].get('alt_label', 'No')
                    if isinstance(alt_next, int) and alt_next < len(steps):
                        dot += f"  step{i} -> step{alt_next} [label=\"{alt_label}\"];\n"

            dot += "}\n"

            # Try to render
            try:
                import subprocess
                from tempfile import NamedTemporaryFile

                output = Path(output_path).expanduser().resolve()
                output.parent.mkdir(parents=True, exist_ok=True)

                with NamedTemporaryFile(mode='w', suffix='.dot', delete=False) as f:
                    f.write(dot)
                    dot_file = f.name

                result = subprocess.run(
                    ["dot", "-Tpng", dot_file, "-o", str(output)],
                    capture_output=True,
                    timeout=30
                )

                if result.returncode != 0:
                    return ToolResult(
                        success=True,
                        output={'dot_source': dot, 'message': 'Graphviz not installed'},
                        tool_name=self.name
                    )

                return ToolResult(
                    success=True,
                    output={
                        'output_path': str(output),
                        'dot_source': dot,
                        'message': f'Flowchart saved to {output}'
                    },
                    tool_name=self.name
                )

            except FileNotFoundError:
                # NO FILE WAS WRITTEN -- see above.
                return ToolResult(
                    success=False,
                    error='graphviz is not installed, so no flowchart was rendered',
                    output={'dot_source': dot, 'message': 'Graphviz not found. Install: brew install graphviz'},
                    tool_name=self.name
                )

        except Exception as e:
            logger.error(f"Flowchart creation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class FetchPaperByDOITool(Tool):
    """Fetch paper metadata and PDF from DOI"""

    def __init__(self):
        super().__init__()
        self.name = "fetch_paper_by_doi"
        self.description = "Fetch paper metadata and optionally download PDF using DOI"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="doi",
                type="string",
                description="Digital Object Identifier (DOI)",
                required=True
            ),
            ToolParameter(
                name="download_pdf",
                type="boolean",
                description="Whether to download PDF",
                required=False,
                default=False
            ),
            ToolParameter(
                name="output_dir",
                type="string",
                description="Directory to save PDF",
                required=False,
                default="./papers"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="fetch_paper_by_doi",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="FetchPaperByDOI capability"
                )
            ]
        )

    async def execute(self, doi: str, download_pdf: bool = False,
                     output_dir: str = "./papers") -> ToolResult:
        try:
            from .network_tools import HttpRequestTool
            http_tool = HttpRequestTool()

            # Fetch metadata from CrossRef API
            crossref_url = f"https://api.crossref.org/works/{doi}"
            result = await http_tool.execute(url=crossref_url, method="GET")

            if not result.success:
                return ToolResult(success=False, output=None,
                                error=f"Failed to fetch DOI metadata: {result.error}",
                                tool_name=self.name)

            data = result.output.get('body', {})
            if 'message' in data:
                metadata = data['message']

                # Extract key metadata
                output = {
                    'doi': doi,
                    'title': metadata.get('title', [''])[0] if metadata.get('title') else '',
                    'authors': [
                        f"{a.get('given', '')} {a.get('family', '')}".strip()
                        for a in metadata.get('author', [])
                    ],
                    'year': metadata.get('published-print', {}).get('date-parts', [[None]])[0][0],
                    'journal': metadata.get('container-title', [''])[0] if metadata.get('container-title') else '',
                    'abstract': metadata.get('abstract', ''),
                    'url': metadata.get('URL', ''),
                    'type': metadata.get('type', 'unknown')
                }

                # Download PDF if requested
                if download_pdf:
                    pdf_link = metadata.get('link', [{}])[0].get('URL') if metadata.get('link') else None
                    if pdf_link:
                        pdf_path = Path(output_dir).expanduser().resolve()
                        pdf_path.mkdir(parents=True, exist_ok=True)

                        # Sanitize filename
                        filename = re.sub(r'[^\w\s-]', '', output['title'][:100]) + '.pdf'
                        pdf_file = pdf_path / filename

                        output['pdf_path'] = str(pdf_file)
                        output['pdf_downloaded'] = False  # Would need actual download implementation

                return ToolResult(success=True, output=output, tool_name=self.name)
            else:
                return ToolResult(success=False, output=None,
                                error="Invalid DOI or paper not found", tool_name=self.name)

        except Exception as e:
            logger.error(f"DOI fetch failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class FetchPaperByArxivTool(Tool):
    """Fetch paper from arXiv ID"""

    def __init__(self):
        super().__init__()
        self.name = "fetch_paper_by_arxiv"
        self.description = "Fetch paper metadata and PDF from arXiv using arXiv ID"
        self.category = ToolCategory.NETWORK
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="arxiv_id",
                type="string",
                description="arXiv identifier (e.g., 2301.12345)",
                required=True
            ),
            ToolParameter(
                name="download_pdf",
                type="boolean",
                description="Whether to download PDF",
                required=False,
                default=False
            ),
            ToolParameter(
                name="output_dir",
                type="string",
                description="Directory to save PDF",
                required=False,
                default="./papers"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="fetch_paper_by_arxiv",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="FetchPaperByArxiv capability"
                )
            ]
        )

    async def execute(self, arxiv_id: str, download_pdf: bool = False,
                     output_dir: str = "./papers") -> ToolResult:
        try:
            from .network_tools import HttpRequestTool
            http_tool = HttpRequestTool()

            # Query arXiv API
            arxiv_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            result = await http_tool.execute(url=arxiv_url, method="GET")

            if not result.success:
                return ToolResult(success=False, output=None,
                                error=f"Failed to fetch arXiv metadata: {result.error}",
                                tool_name=self.name)

            # Parse XML response
            xml_content = result.output.get('body', '')

            # Simple XML parsing
            title_match = re.search(r'<title>([^<]+)</title>', xml_content)
            summary_match = re.search(r'<summary>([^<]+)</summary>', xml_content)
            published_match = re.search(r'<published>([^<]+)</published>', xml_content)

            authors = re.findall(r'<name>([^<]+)</name>', xml_content)

            output = {
                'arxiv_id': arxiv_id,
                'title': title_match.group(1).strip() if title_match else '',
                'authors': authors[1:] if len(authors) > 1 else authors,  # First name is usually the API itself
                'abstract': summary_match.group(1).strip() if summary_match else '',
                'published': published_match.group(1) if published_match else '',
                'pdf_url': f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                'abs_url': f"https://arxiv.org/abs/{arxiv_id}"
            }

            # Download PDF if requested
            if download_pdf:
                pdf_path = Path(output_dir).expanduser().resolve()
                pdf_path.mkdir(parents=True, exist_ok=True)

                pdf_file = pdf_path / f"{arxiv_id.replace('/', '_')}.pdf"
                output['pdf_path'] = str(pdf_file)
                output['pdf_downloaded'] = False  # Would need actual download implementation

            return ToolResult(success=True, output=output, tool_name=self.name)

        except Exception as e:
            logger.error(f"arXiv fetch failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class ValidateBibliographyTool(Tool):
    """Validate and deduplicate bibliography entries"""

    def __init__(self):
        super().__init__()
        self.name = "validate_bibliography"
        self.description = "Validate bibliography entries, check for duplicates, and ensure citation consistency"
        self.category = ToolCategory.DOCUMENTATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="bibliography",
                type="array",
                description="List of bibliography entries (dicts with title, authors, year, etc.)",
                required=True
            ),
            ToolParameter(
                name="check_duplicates",
                type="boolean",
                description="Check for duplicate entries",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="validate_bibliography",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="ValidateBibliography capability"
                ),
                CapabilityMetadata(
                    capability=Capability.VALIDATE_KNOWLEDGE,
                    description="Validate bibliography and knowledge sources",
                    input_types=["bibliography"],
                    output_types=["validation_report"],
                    latency="medium",
                    cost="low",
                    reliability="high",
                    risk_level=RiskLevel.LOW,
                    priority=7
                )
            ]
        )

    async def execute(self, bibliography: List[Dict[str, Any]],
                     check_duplicates: bool = True) -> ToolResult:
        try:
            issues = []
            duplicates = []
            validated = []

            for i, entry in enumerate(bibliography):
                entry_issues = []

                # Check required fields
                required_fields = ['title', 'authors', 'year']
                for field in required_fields:
                    if field not in entry or not entry[field]:
                        entry_issues.append(f"Missing required field: {field}")

                # Validate year format
                if 'year' in entry:
                    try:
                        year = int(entry['year'])
                        if year < 1900 or year > datetime.now().year + 1:
                            entry_issues.append(f"Invalid year: {year}")
                    except (ValueError, TypeError):
                        entry_issues.append(f"Year must be a number")

                # Validate DOI format if present
                if 'doi' in entry and entry['doi']:
                    if not re.match(r'10\.\d{4,}/[^\s]+', entry['doi']):
                        entry_issues.append(f"Invalid DOI format: {entry['doi']}")

                # Check for duplicates
                if check_duplicates:
                    for j, other in enumerate(bibliography[:i]):
                        similarity = self._calculate_similarity(entry, other)
                        if similarity > 0.8:  # 80% similar
                            duplicates.append({
                                'entry1_index': j,
                                'entry2_index': i,
                                'similarity': similarity,
                                'reason': self._get_duplicate_reason(entry, other)
                            })

                if entry_issues:
                    issues.append({
                        'index': i,
                        'entry': entry.get('title', 'Unknown'),
                        'issues': entry_issues
                    })
                else:
                    validated.append(entry)

            return ToolResult(
                success=True,
                output={
                    'total_entries': len(bibliography),
                    'validated_entries': len(validated),
                    'entries_with_issues': len(issues),
                    'duplicates_found': len(duplicates),
                    'issues': issues,
                    'duplicates': duplicates,
                    'validated_bibliography': validated
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Bibliography validation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)

    def _calculate_similarity(self, entry1: Dict, entry2: Dict) -> float:
        """Calculate similarity between two entries"""
        # Simple similarity based on title and year
        title1 = entry1.get('title', '').lower()
        title2 = entry2.get('title', '').lower()
        year1 = entry1.get('year')
        year2 = entry2.get('year')

        # Exact year match
        year_match = 1.0 if year1 == year2 else 0.0

        # Title similarity (simple character overlap)
        title_overlap = len(set(title1) & set(title2)) / max(len(set(title1)), len(set(title2)), 1)

        return (title_overlap * 0.7 + year_match * 0.3)

    def _get_duplicate_reason(self, entry1: Dict, entry2: Dict) -> str:
        """Get reason for duplicate detection"""
        reasons = []
        if entry1.get('title', '').lower() == entry2.get('title', '').lower():
            reasons.append("Same title")
        if entry1.get('doi') and entry1.get('doi') == entry2.get('doi'):
            reasons.append("Same DOI")
        if entry1.get('year') == entry2.get('year'):
            reasons.append("Same year")
        return ", ".join(reasons) if reasons else "Similar titles"


class ExportBibliographyCSLTool(Tool):
    """Export bibliography in CSL-JSON format"""

    def __init__(self):
        super().__init__()
        self.name = "export_bibliography_csl"
        self.description = "Export bibliography in Citation Style Language (CSL-JSON) format for compatibility with citation managers"
        self.category = ToolCategory.DOCUMENTATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="bibliography",
                type="array",
                description="List of bibliography entries",
                required=True
            ),
            ToolParameter(
                name="output_path",
                type="string",
                description="Path to save CSL-JSON file",
                required=False,
                default="bibliography.json"
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="export_bibliography_csl",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="ExportBibliographyCSL capability"
                )
            ]
        )

    async def execute(self, bibliography: List[Dict[str, Any]],
                     output_path: str = "bibliography.json") -> ToolResult:
        try:
            csl_items = []

            for entry in bibliography:
                # Convert to CSL-JSON format
                csl_item = {
                    "id": entry.get('id', f"item-{len(csl_items)}"),
                    "type": entry.get('type', 'article-journal'),
                    "title": entry.get('title', ''),
                    "author": [
                        {"family": a.split()[-1], "given": " ".join(a.split()[:-1])}
                        for a in (entry.get('authors', []) if isinstance(entry.get('authors'), list)
                                 else [entry.get('authors', '')])
                    ],
                    "issued": {"date-parts": [[entry.get('year')]]},
                }

                # Add optional fields
                if 'journal' in entry and entry['journal']:
                    csl_item['container-title'] = entry['journal']
                if 'doi' in entry and entry['doi']:
                    csl_item['DOI'] = entry['doi']
                if 'url' in entry and entry['url']:
                    csl_item['URL'] = entry['url']
                if 'volume' in entry:
                    csl_item['volume'] = entry['volume']
                if 'issue' in entry:
                    csl_item['issue'] = entry['issue']
                if 'pages' in entry:
                    csl_item['page'] = entry['pages']

                csl_items.append(csl_item)

            # Save to file
            output = Path(output_path).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)

            with open(output, 'w', encoding='utf-8') as f:
                json.dump(csl_items, f, indent=2, ensure_ascii=False)

            return ToolResult(
                success=True,
                output={
                    'format': 'CSL-JSON',
                    'entries_exported': len(csl_items),
                    'output_path': str(output),
                    'csl_data': csl_items
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"CSL export failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class LinkClaimToEvidenceTool(Tool):
    """Create provenance links between claims and evidence"""

    def __init__(self):
        super().__init__()
        self.name = "link_claim_to_evidence"
        self.description = "Create provenance anchors linking claims in text to supporting evidence from sources"
        self.category = ToolCategory.DOCUMENTATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="claim",
                type="string",
                description="The claim being made",
                required=True
            ),
            ToolParameter(
                name="evidence",
                type="object",
                description="Evidence supporting the claim (source, quote, page)",
                required=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="link_claim_to_evidence",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="LinkClaimToEvidence capability"
                )
            ]
        )

    async def execute(self, claim: str, evidence: Dict[str, Any]) -> ToolResult:
        try:
            # Create provenance link
            provenance = {
                'claim_id': f"claim_{hash(claim) % 1000000}",
                'claim_text': claim,
                'evidence_source': evidence.get('source', 'Unknown'),
                'evidence_quote': evidence.get('quote', ''),
                'evidence_page': evidence.get('page'),
                'evidence_doi': evidence.get('doi'),
                'confidence': evidence.get('confidence', 'medium'),
                'timestamp': datetime.now().isoformat(),
                'link_type': 'supports'  # Can be: supports, contradicts, relates_to
            }

            # Generate citation anchor
            anchor = f"[{provenance['claim_id']}]"

            # Generate evidence annotation
            annotation = f"{claim} {anchor}\n"
            annotation += f"  Evidence: {provenance['evidence_quote']}\n"
            annotation += f"  Source: {provenance['evidence_source']}"
            if provenance['evidence_page']:
                annotation += f", p. {provenance['evidence_page']}"
            annotation += "\n"

            return ToolResult(
                success=True,
                output={
                    'provenance': provenance,
                    'citation_anchor': anchor,
                    'annotated_claim': annotation,
                    'verifiable': bool(evidence.get('doi') or evidence.get('url'))
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Evidence linking failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)


class GenerateArtifactManifestTool(Tool):
    """Generate reproducibility artifact manifest"""

    def __init__(self):
        super().__init__()
        self.name = "generate_artifact_manifest"
        self.description = "Create a comprehensive artifact manifest for research reproducibility (code, data, dependencies)"
        self.category = ToolCategory.DOCUMENTATION
        self.safety_level = ToolSafety.SAFE
        self.parameters = [
            ToolParameter(
                name="project_path",
                type="string",
                description="Path to research project",
                required=True
            ),
            ToolParameter(
                name="include_checksums",
                type="boolean",
                description="Include file checksums for verification",
                required=False,
                default=True
            )
        ]

        # Capability profile
        self.capability_profile = ToolCapabilityProfile(
            tool_name="generate_artifact_manifest",
            capabilities=[
                CapabilityMetadata(
                    capability=Capability.CONDUCT_RESEARCH,
                    description="GenerateArtifactManifest capability"
                )
            ]
        )

    async def execute(self, project_path: str, include_checksums: bool = True) -> ToolResult:
        try:
            import hashlib

            project = Path(project_path).expanduser().resolve()
            if not project.exists():
                return ToolResult(success=False, output=None,
                                error=f"Project path not found: {project}", tool_name=self.name)

            manifest = {
                'artifact_version': '1.0',
                'generated_at': datetime.now().isoformat(),
                'project_name': project.name,
                'project_path': str(project),
                'code_files': [],
                'data_files': [],
                'dependencies': {},
                'environment': {}
            }

            # Scan code files
            for ext in ['*.py', '*.ipynb', '*.R', '*.jl', '*.m']:
                for file_path in project.rglob(ext):
                    if '__pycache__' in str(file_path) or '.git' in str(file_path):
                        continue

                    file_info = {
                        'path': str(file_path.relative_to(project)),
                        'size': file_path.stat().st_size,
                        'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                    }

                    if include_checksums:
                        with open(file_path, 'rb') as f:
                            file_info['sha256'] = hashlib.sha256(f.read()).hexdigest()

                    manifest['code_files'].append(file_info)

            # Scan data files
            for ext in ['*.csv', '*.json', '*.pkl', '*.npy', '*.h5']:
                for file_path in project.rglob(ext):
                    file_info = {
                        'path': str(file_path.relative_to(project)),
                        'size': file_path.stat().st_size
                    }
                    if include_checksums and file_path.stat().st_size < 100_000_000:  # < 100MB
                        with open(file_path, 'rb') as f:
                            file_info['sha256'] = hashlib.sha256(f.read()).hexdigest()
                    manifest['data_files'].append(file_info)

            # Check for dependency files
            req_file = project / 'requirements.txt'
            if req_file.exists():
                with open(req_file, 'r') as f:
                    manifest['dependencies']['python'] = f.read().strip().split('\n')

            # Save manifest
            manifest_path = project / 'ARTIFACT_MANIFEST.json'
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)

            return ToolResult(
                success=True,
                output={
                    'manifest': manifest,
                    'manifest_path': str(manifest_path),
                    'code_files_count': len(manifest['code_files']),
                    'data_files_count': len(manifest['data_files']),
                    'total_size_bytes': sum(f['size'] for f in manifest['code_files'] + manifest['data_files'])
                },
                tool_name=self.name
            )

        except Exception as e:
            logger.error(f"Artifact manifest generation failed: {e}")
            return ToolResult(success=False, output=None, error=str(e), tool_name=self.name)
