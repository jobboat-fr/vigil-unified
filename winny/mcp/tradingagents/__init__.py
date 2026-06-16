"""mcp-tradingagents — Reasoning service wrapping TradingAgents LangGraph.

Exposes:
    - analyze_symbol:       Full multi-agent analysis → DecisionDraft
    - debate_position:      Follow-up debate on a prior decision
    - get_decision_history: Read back past decisions from memory

Per §3.2, this server is read-only — it produces recommendations but
never places orders or modifies any external state.
"""
