"""Evaluare imobiliară: serverul MCP (`mcp/`) și API-ul HTTP peste el (`api/`).

Separat de `gemini_act` pentru că este un produs în sine — are propriul server
MCP, propriul script de consolă (`imobiliare-mcp`) și propriile dependențe grele
(reportlab, pypdf, python-docx, pillow). `gemini_act` îl folosește ca tool;
dependența merge doar în sensul acela, niciodată invers.
"""
