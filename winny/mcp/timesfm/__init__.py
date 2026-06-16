"""mcp-timesfm — TimesFM 2.5 forecasting MCP server per §3.1.

This package implements the walking-skeleton MCP server that wraps Google's
TimesFM 2.5 200M model for time-series forecasting. It is asset-agnostic at
the model level: input = numeric series + horizon, output = quantile forecast.

Public tools:
    forecast_series  — raw numeric input, no symbol semantics
    forecast_symbol  — convenience wrapper that pulls history via data layer

Architecture (§3.1):
    Model: google/timesfm-2.5-200m-pytorch (Apache-2.0, 200M params)
    Defaults: max_context=1024, max_horizon=256, normalize_inputs=True
    Quantiles: mean + deciles 0.1…0.9 → shape (B, H, 10)
    Transport: MCP over stdio (JSON-RPC 2.0)
"""
