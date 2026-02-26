## ─────────────────────────────────────────────────────────────────────────────
## task.py  —  All CrewAI tasks for the Financial Document Analyzer
## ─────────────────────────────────────────────────────────────────────────────
from crewai import Task

from agents import financial_analyst, verifier, investment_advisor, risk_assessor, market_analyst
from tools import FinancialDocumentTool, InvestmentTool, RiskTool, search_tool

# ── Task 1: Document Verification ────────────────────────────────────────────
verification = Task(
    description=(
        "Use the Financial Document Reader tool to open and read the PDF at path: {file_path}.\n"
        "Carefully examine its contents and determine:\n"
        "  1. Whether this is a genuine financial document (annual report, quarterly earnings, "
        "     income statement, balance sheet, cash flow statement, or similar).\n"
        "  2. The name of the reporting entity.\n"
        "  3. The reporting period covered (e.g. Q2 2025, FY 2024).\n"
        "  4. Which financial sections are present (e.g. income statement, balance sheet, "
        "     cash flow, notes to accounts).\n"
        "  5. Any obvious data quality issues (missing sections, illegible text, corrupted pages).\n"
        "If the document is NOT a financial report, state this clearly and stop."
    ),
    expected_output=(
        "A concise verification report:\n"
        "- VERDICT: [Confirmed Financial Document / Not a Financial Document]\n"
        "- Entity: [company or organisation name]\n"
        "- Document Type: [e.g. Quarterly Earnings Release]\n"
        "- Reporting Period: [e.g. Q2 2025]\n"
        "- Sections Identified: [list]\n"
        "- Data Quality Notes: [issues or 'None identified']"
    ),
    agent=verifier,
    tools=[FinancialDocumentTool.read_data_tool],
    async_execution=False,
)

# ── Task 2: Core Financial Analysis ──────────────────────────────────────────
analyze_financial_document = Task(
    description=(
        "Using the verified financial document at path: {file_path}, produce a thorough "
        "financial analysis that directly answers the user's query: {query}.\n\n"
        "  1. Use the Financial Document Reader tool to read the document.\n"
        "  2. Extract all relevant metrics: revenue, gross profit, operating income, net income, "
        "     EPS, EBITDA, free cash flow, total assets, liabilities, equity, and key ratios.\n"
        "  3. Identify year-over-year or quarter-over-quarter trends where available.\n"
        "  4. Flag any one-off items, restatements, or non-recurring charges.\n"
        "  5. Support every finding with a specific figure and source section.\n"
        "  6. Do NOT fabricate figures or make projections beyond what the document states."
    ),
    expected_output=(
        "Structured financial analysis report:\n"
        "- EXECUTIVE SUMMARY: 2–3 sentences answering the query\n"
        "- KEY METRICS: Figures with document section references\n"
        "- TREND ANALYSIS: Period-over-period changes with % deltas\n"
        "- NOTABLE ITEMS: One-off events or unusual line items\n"
        "- ANALYSIS LIMITATIONS: What could not be determined"
    ),
    agent=financial_analyst,
    tools=[FinancialDocumentTool.read_data_tool],
    context=[verification],
    async_execution=False,
)

# ── Task 3: Investment Insights ───────────────────────────────────────────────
investment_analysis = Task(
    description=(
        "Using the financial analysis produced in the previous task, provide objective "
        "investment insights relevant to: {query}.\n\n"
        "  1. Run the Investment Analyzer tool on the document text from: {file_path}.\n"
        "  2. Review the extracted metrics AND the prior financial analysis output.\n"
        "  3. Identify investment signals: revenue trajectory, margin changes, cash generation, "
        "     balance sheet strength, and capital allocation.\n"
        "  4. Present both bull-case and bear-case considerations grounded in the data.\n"
        "  5. Do NOT recommend specific buy/sell actions or guarantee returns.\n"
        "  6. End with a mandatory disclaimer that this is informational analysis only."
    ),
    expected_output=(
        "Investment insight report:\n"
        "- INVESTMENT CONTEXT: What the financials reveal for investors\n"
        "- BULL CASE: Key strengths with figures\n"
        "- BEAR CASE: Key concerns with figures\n"
        "- VALUATION CONSIDERATIONS: P/E, EV/EBITDA or similar if available\n"
        "- DISCLAIMER: Not personalised investment advice"
    ),
    agent=investment_advisor,
    tools=[FinancialDocumentTool.read_data_tool, InvestmentTool.analyze_investment_tool],
    context=[verification, analyze_financial_document],
    async_execution=False,
)

# ── Task 4: Risk Assessment ───────────────────────────────────────────────────
risk_assessment = Task(
    description=(
        "Using the financial document at path: {file_path} and all prior analysis, identify and "
        "assess the key risks relevant to: {query}.\n\n"
        "  1. Run the Risk Assessor tool on the document text from: {file_path}.\n"
        "  2. Classify risks: Financial (liquidity, leverage, credit), Market (concentration, "
        "     competition, FX), Operational (supply chain, regulatory, key-person).\n"
        "  3. Cite evidence for each risk from the document or signal output.\n"
        "  4. Assign severity: High / Medium / Low with one-sentence justification.\n"
        "  5. Note mitigating factors disclosed by the company.\n"
        "  6. Base all ratings on data — never exaggerate or dismiss without evidence."
    ),
    expected_output=(
        "Structured risk assessment:\n"
        "- RISK SUMMARY: Top 3 risks in one paragraph\n"
        "- RISK REGISTER: Per risk — name, category, evidence, severity + justification, mitigants\n"
        "- MONITORING RECOMMENDATIONS: 2–3 metrics or triggers to watch"
    ),
    agent=risk_assessor,
    tools=[FinancialDocumentTool.read_data_tool, RiskTool.create_risk_assessment_tool],
    context=[verification, analyze_financial_document],
    async_execution=False,
)

# ── Task 5: Market Insights ───────────────────────────────────────────────────
market_insights = Task(
    description=(
        "Using the entity and sector identified during verification, research current market "
        "context relevant to: {query}.\n\n"
        "  1. Search for recent news about the company (last 30–90 days).\n"
        "  2. Search for sector and industry trends relevant to this business.\n"
        "  3. Search for macroeconomic factors: interest rates, inflation, FX, regulation.\n"
        "  4. Cross-reference findings with internal financial analysis.\n"
        "  5. Cite every claim with a real, verifiable source (publication + date). "
        "     Never fabricate URLs, publication names, or quotes."
    ),
    expected_output=(
        "Market intelligence report:\n"
        "- COMPANY NEWS SUMMARY: Key recent developments with sources\n"
        "- SECTOR TRENDS: 2–3 material sector trends with sources\n"
        "- MACRO CONTEXT: Relevant macroeconomic factors and directional impact\n"
        "- INTERNAL vs EXTERNAL ALIGNMENT: Where market context supports or challenges financials\n"
        "- SOURCES: All sources used (publication, title, date)"
    ),
    agent=market_analyst,
    tools=[search_tool],
    context=[verification, analyze_financial_document],
    async_execution=False,
)