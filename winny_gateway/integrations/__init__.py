"""External integrations for the gateway — bank/accounting data connectors.

The finance connector (Plaid for bank accounts via API; provider-abstracted so
QuickBooks/Xero accounting can plug in) lets the Finance department pull real
transactions to reconcile. Platform keys come from gateway env (PLAID_*); the
per-user access token is stored encrypted (winny_gateway.integrations.secrets).
"""
