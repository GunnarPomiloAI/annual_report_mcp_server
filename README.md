# Annual Report MCP Server

En MCP-server för att Claude For Desktop ska kunna "chatta med" och analysera årsredovisningar och organisationsdata hos Bolagsverket. Servern exponerar 3 verktyg, sk MCP Tools.

Notera att Servern inte är till för produktion, då den inte hanterar nedladdad data optimalt. Se det som en demo eller exempel på vad som kan göras med MCP.

Bolagsverkets API-tjänst Värdefulla Datamängder används, vilket kräver access som fås genom ansökan hos Bolagsverket.

Tavily kräver också en API, vilket kan fås gratis för forsknings- och testsyfte.

Dessutom används även OpenAI av Llamaindex (det går att ändra till annan LLM API) vilket kräver OpenAI API.

## Funktioner

- Hämta organisationsdata från Bolagsverket
- Hämta och analysera årsredovisningar
- Identifiera organisationsnummer utifrån bolagsnamn via Tavily API
- Automatisk tokenhantering för API-anrop

## Installation

1. Klona repot:
```bash
git clone [repository-url]
cd annual-report-mcp-server
```

2. Installera beroenden:
```bash
pip install -r requirements.txt
```

3. Skapa en `.env` fil med följande variabler:
```
OPENAI_API_KEY=din_openai_key (används av llamaindex för att vektorisera)
BV_CLIENT_ID=din_client_id
BV_CLIENT_SECRET=din_client_secret
TAVILY_API_KEY=din_tavily_api_key
```

## Installation i Claude for Desktop

Ladda ner och installera Claude For Desktop.

Installera MCP servern i Claude For Desktop:

mcp install annual-report-mcp-server.py

Eventuellt kan det bli problem med dependencies, uv och PATH.

Ändra då manuellt i claude_desktop_config.json (den skapas när servern installeras)

{
  "mcpServers": {
    "annual_report_mcp_server": {
      "command": "/bin/bash",
      "args": [
        "-c",
        "source ABSOLUTE PATH/.venv/bin/activate && ABSOLUTE PATH/.local/bin/uv run --with mcp[cli] mcp run ABSOLUTE PATH/annual_report_mcp_server.py"
      ]
    }
  }
}

## Beroenden

- beautifulsoup4>=4.12.0
- lxml>=4.9.0
- requests>=2.31.0
- python-dotenv>=1.0.0
- llama-index>=0.10.0
- mcp>=0.1.0
- tavily-python>=0.3.0

## Licens

MIT
