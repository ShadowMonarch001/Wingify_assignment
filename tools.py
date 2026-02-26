## ─────────────────────────────────────────────────────────────────────────────
## tools.py  —  All CrewAI tools for the Financial Document Analyzer
## ─────────────────────────────────────────────────────────────────────────────
import re
from dotenv import load_dotenv
load_dotenv()

from crewai.tools import tool
from crewai_tools import SerperDevTool
from langchain_community.document_loaders import PyPDFLoader

## ── Web search tool (used by market_analyst agent) ───────────────────────────
search_tool = SerperDevTool()


## ── PDF Reader Tool ───────────────────────────────────────────────────────────
# IMPORTANT: CrewAI's @tool decorator must be applied to a standalone module-level
# function. Stacking @staticmethod + @tool inside a class breaks tool registration
# in crewai 0.130.0. Each tool is defined as a module-level function and then
# assigned as a class attribute so agents can reference it as ClassName.tool_name.

@tool("Financial Document Reader")
def _read_data_tool(path: str = "data/sample.pdf") -> str:
    """Read and extract the full text content from a financial PDF document.

    Use this tool to load a PDF file and return its full text for analysis.
    Always pass the exact file path received from the task context.

    Args:
        path: File system path to the PDF. Defaults to 'data/sample.pdf'.

    Returns:
        The complete extracted text of the financial document, or an error message.
    """
    try:
        loader = PyPDFLoader(file_path=path)
        docs = loader.load()
    except Exception as e:
        return f"ERROR: Could not load PDF at '{path}'. Reason: {e}"

    if not docs:
        return f"ERROR: No content extracted from '{path}'. File may be empty or corrupt."

    full_report = ""
    for page in docs:
        content = page.page_content
        while "\n\n" in content:
            content = content.replace("\n\n", "\n")
        full_report += content + "\n"

    return full_report.strip()


class FinancialDocumentTool:
    """Namespace so agents reference the tool as FinancialDocumentTool.read_data_tool."""
    read_data_tool = _read_data_tool


## ── Investment Analyzer Tool ──────────────────────────────────────────────────

@tool("Investment Analyzer")
def _analyze_investment_tool(financial_document_data: str) -> str:
    """Pre-process and structure raw financial document text for investment analysis.

    Cleans whitespace noise, extracts key numeric financial metrics using pattern
    matching, and returns a structured summary ready for the investment advisor agent.

    Args:
        financial_document_data: Raw text extracted from a financial document.

    Returns:
        A cleaned, structured string with extracted metrics and sanitised full text.
    """
    if not financial_document_data or not financial_document_data.strip():
        return "ERROR: No financial data provided for investment analysis."

    # Clean whitespace
    processed = re.sub(r"  +", " ", financial_document_data)
    processed = re.sub(r"\r\n|\r", "\n", processed)
    processed = re.sub(r"\n{3,}", "\n\n", processed)
    processed = processed.strip()

    # Extract labelled currency values and percentage metrics
    currency_pattern = re.compile(
        r"(?:revenue|sales|income|profit|loss|ebitda|cash|earnings|eps|margin)"
        r"[^\n]{0,60}"
        r"(?:\$|€|£|USD|EUR|GBP)?\s*[\d,]+(?:\.\d+)?\s*(?:billion|million|thousand|bn|mn|k)?",
        re.IGNORECASE,
    )
    percent_pattern = re.compile(
        r"(?:growth|margin|change|increase|decrease|yoy|qoq|return|rate)"
        r"[^\n]{0,40}[\d,]+(?:\.\d+)?\s*%",
        re.IGNORECASE,
    )

    seen: set = set()
    key_metrics: list = []
    for m in currency_pattern.findall(processed) + percent_pattern.findall(processed):
        m_clean = m.strip()
        if m_clean not in seen:
            seen.add(m_clean)
            key_metrics.append(m_clean)

    metrics_section = (
        "=== EXTRACTED KEY METRICS ===\n" +
        "\n".join(f"  • {m}" for m in key_metrics[:30])
        if key_metrics
        else "=== EXTRACTED KEY METRICS ===\n  (No metrics auto-extracted — agent should parse full text.)"
    )

    return f"{metrics_section}\n\n=== CLEANED FULL TEXT ===\n{processed}"


class InvestmentTool:
    """Namespace for the investment analysis tool."""
    analyze_investment_tool = _analyze_investment_tool


## ── Risk Assessment Tool ─────────────────────────────────────────────────────

@tool("Risk Assessor")
def _create_risk_assessment_tool(financial_document_data: str) -> str:
    """Pre-process financial text and surface risk-relevant signals for assessment.

    Scans for common financial risk indicators across 8 categories and returns
    a structured signal report alongside the cleaned full text.

    Args:
        financial_document_data: Raw text extracted from a financial document.

    Returns:
        A structured string with flagged risk signals and sanitised full text.
    """
    if not financial_document_data or not financial_document_data.strip():
        return "ERROR: No financial data provided for risk assessment."

    processed = re.sub(r"  +", " ", financial_document_data)
    processed = re.sub(r"\r\n|\r", "\n", processed)
    processed = re.sub(r"\n{3,}", "\n\n", processed)
    processed = processed.strip()

    risk_signals: dict[str, list[str]] = {
        "Leverage / Debt": [],
        "Liquidity": [],
        "Revenue Concentration": [],
        "Regulatory / Legal": [],
        "Going Concern": [],
        "Covenants / Defaults": [],
        "Operational": [],
        "Market / FX": [],
    }

    risk_patterns: list[tuple[str, re.Pattern]] = [
        ("Leverage / Debt",       re.compile(r".{0,80}(?:debt[- ]to[- ]equity|leverage ratio|long[- ]term debt|net debt|gearing)[^\n]{0,100}", re.IGNORECASE)),
        ("Liquidity",             re.compile(r".{0,80}(?:current ratio|quick ratio|liquidity|cash and cash equivalents|working capital)[^\n]{0,100}", re.IGNORECASE)),
        ("Revenue Concentration", re.compile(r".{0,80}(?:customer concentration|single customer|top \d+ customer|revenue concentration)[^\n]{0,100}", re.IGNORECASE)),
        ("Regulatory / Legal",    re.compile(r".{0,80}(?:lawsuit|litigation|regulatory|investigation|penalty|fine|sec|ftc|doj|compliance risk)[^\n]{0,100}", re.IGNORECASE)),
        ("Going Concern",         re.compile(r".{0,80}(?:going concern|substantial doubt|ability to continue|material uncertainty)[^\n]{0,100}", re.IGNORECASE)),
        ("Covenants / Defaults",  re.compile(r".{0,80}(?:covenant|default|waiver|breach|cross[- ]default|acceleration)[^\n]{0,100}", re.IGNORECASE)),
        ("Operational",           re.compile(r".{0,80}(?:supply chain|disruption|key personnel|key employee|single[- ]source|manufacturing risk)[^\n]{0,100}", re.IGNORECASE)),
        ("Market / FX",           re.compile(r".{0,80}(?:foreign exchange|currency risk|fx|interest rate risk|commodity price|inflation risk)[^\n]{0,100}", re.IGNORECASE)),
    ]

    for category, pattern in risk_patterns:
        seen_local: set = set()
        for m in pattern.findall(processed):
            m_clean = m.strip()
            if m_clean not in seen_local:
                seen_local.add(m_clean)
                risk_signals[category].append(m_clean)
                if len(risk_signals[category]) >= 5:
                    break

    signal_lines: list[str] = []
    total_signals = 0
    for category, signals in risk_signals.items():
        if signals:
            signal_lines.append(f"\n  [{category}]")
            for s in signals:
                signal_lines.append(f"    ↳ {s}")
                total_signals += 1

    signals_section = (
        f"=== RISK SIGNALS DETECTED ({total_signals} total) ===\n" + "\n".join(signal_lines)
        if signal_lines
        else "=== RISK SIGNALS DETECTED ===\n  (No standard risk keywords detected. Agent should assess full text.)"
    )

    return f"{signals_section}\n\n=== CLEANED FULL TEXT ===\n{processed}"


class RiskTool:
    """Namespace for the risk assessment tool."""
    create_risk_assessment_tool = _create_risk_assessment_tool