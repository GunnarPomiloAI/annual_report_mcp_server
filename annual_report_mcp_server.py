import os
import time
import requests
import zipfile
import io
from dotenv import load_dotenv
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import lxml
import warnings
from llama_index.core import Document, VectorStoreIndex, StorageContext, load_index_from_storage
from mcp.server.fastmcp import FastMCP
from tavily import TavilyClient

# Load environment variables
load_dotenv()

# Define storage directory
STORAGE_DIR = os.path.expanduser("~/Library/Application Support/Claude/Local Storage/Annual Reports Data")
os.makedirs(STORAGE_DIR, exist_ok=True)

# Create an MCP server
mcp = FastMCP("AnnualReportServer")

# Funktioner för API-anrop med tokenhantering och felhantering
class TokenManager:
    def __init__(self):
        self.token = None
        self.expiry_time = 0

    def get_access_token(self):
        current_time = time.time()
        if self.token and current_time < self.expiry_time:
            return self.token

        token_url = "https://portal.api.bolagsverket.se/oauth2/token"
        data = {
            'grant_type': 'client_credentials',
            'client_id': os.getenv('BV_CLIENT_ID'),
            'client_secret': os.getenv('BV_CLIENT_SECRET'),
            'scope': 'vardefulla-datamangder:read vardefulla-datamangder:ping'
        }
        response = requests.post(token_url, data=data)
        response.raise_for_status()
        token_result = response.json()
        self.token = token_result['access_token']
        self.expiry_time = current_time + token_result.get('expires_in', 3600)
        return self.token

# Global token manager instance
token_manager = TokenManager()

def fetch_organisation_data(org_no):
    token = token_manager.get_access_token()
    url = "https://gw.api.bolagsverket.se/vardefulla-datamangder/v1/organisationer"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    payload = {"identitetsbeteckning": org_no}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.Timeout:
        print("Fel: Begäran tog för lång tid.")
        raise
    except requests.HTTPError as e:
        print(f"HTTPError: {e}")
        print("API Response:", response.text)
        raise
    except requests.RequestException as e:
        print(f"Fel vid API-anrop: {e}")
        raise

    return response.json()

def fetch_annual_report(org_no, year):
    token = token_manager.get_access_token()
    dokumentlista_url = "https://gw.api.bolagsverket.se/vardefulla-datamangder/v1/dokumentlista"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    payload = {"identitetsbeteckning": org_no}
    dokumentlista_response = requests.post(dokumentlista_url, json=payload, headers=headers)
    dokumentlista_response.raise_for_status()
    dokumentlista = dokumentlista_response.json()
    
    target_doc_id = None
    for doc in dokumentlista.get("dokument", []):
        rap_period = doc.get("rapporteringsperiodTom", "")
        if rap_period.startswith(str(year)):
            target_doc_id = doc.get("dokumentId")
            break
    if not target_doc_id:
        raise ValueError(f"Inget dokument hittades för år {year} för organisation {org_no}. Det beror på att bolaget inte lämnat in ÅR digitalt.")
    
    document_url = f"https://gw.api.bolagsverket.se/vardefulla-datamangder/v1/dokument/{target_doc_id}"
    headers_doc = {
        'Authorization': f'Bearer {token}'
    }
    document_response = requests.get(document_url, headers=headers_doc)
    document_response.raise_for_status()

    zip_data = io.BytesIO(document_response.content)
    with zipfile.ZipFile(zip_data, 'r') as zip_ref:
        file_list = zip_ref.namelist()
        xhtml_file = None
        for file in file_list:
            if file.lower().endswith('.xhtml'):
                xhtml_file = file
                break
        if not xhtml_file:
            raise ValueError("Inga XHTML-filer hittades i zip-arkivet.")
        file_content = zip_ref.read(xhtml_file)
        
        output_filename = os.path.join(STORAGE_DIR, f"{org_no}_{year}.xhtml")
        with open(output_filename, "wb") as f:
            f.write(file_content)
    
    return output_filename

# Parse XHTML file and extract relevant text and numbers
def parse_xhtml(file_path):
    """
    Parse XHTML file from annual reports with improved handling of tables and structure.
    
    Args:
        file_path: Path to the XHTML file
        
    Returns:
        A string containing the parsed content with preserved structure
    """
    # Ignore XML parsing warnings
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        soup = BeautifulSoup(content, 'lxml-xml')  # Use lxml-xml parser for XML documents

    # Remove unnecessary elements
    for tag in soup(['script', 'style', 'header', 'footer', 'nav']):
        tag.decompose()
    
    # Process the document by sections
    sections = []
    
    # Extract headings and create a hierarchical structure
    headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    
    # Process paragraphs and other text content
    paragraphs = soup.find_all('p')
    for p in paragraphs:
        text = ' '.join(p.stripped_strings)
        if text:
            sections.append(text)
    
    # Process lists
    lists = soup.find_all(['ul', 'ol'])
    for list_elem in lists:
        list_items = list_elem.find_all('li')
        list_type = 'ul' if list_elem.name == 'ul' else 'ol'
        list_text = []
        
        for i, item in enumerate(list_items):
            prefix = '• ' if list_type == 'ul' else f"{i+1}. "
            item_text = ' '.join(item.stripped_strings)
            if item_text:
                list_text.append(f"{prefix}{item_text}")
        
        if list_text:
            sections.append('\n'.join(list_text))
    
    # Special handling for tables
    tables = soup.find_all('table')
    for table in tables:
        table_sections = []
        
        # Try to find table caption or title
        caption = table.find('caption')
        if caption:
            caption_text = ' '.join(caption.stripped_strings)
            if caption_text:
                table_sections.append(f"TABLE: {caption_text}")
        
        # Process table headers
        headers = []
        th_elements = table.find_all('th')
        if th_elements:
            for th in th_elements:
                header_text = ' '.join(th.stripped_strings)
                headers.append(header_text)
        
        # Process table rows
        rows = table.find_all('tr')
        for row in rows:
            row_data = []
            
            # Process cells (td elements)
            cells = row.find_all(['td', 'th'])
            for cell in cells:
                # Check for rowspan and colspan
                rowspan = cell.get('rowspan')
                colspan = cell.get('colspan')
                
                cell_text = ' '.join(cell.stripped_strings)
                
                # Add span information if present
                if rowspan or colspan:
                    span_info = []
                    if rowspan and int(rowspan) > 1:
                        span_info.append(f"rowspan={rowspan}")
                    if colspan and int(colspan) > 1:
                        span_info.append(f"colspan={colspan}")
                    
                    if span_info:
                        cell_text = f"{cell_text} [{', '.join(span_info)}]"
                
                row_data.append(cell_text)
            
            if row_data:
                # Format the row as a pipe-separated string (markdown-like table format)
                table_sections.append(" | ".join(row_data))
        
        # Add separator line if we have headers
        if headers and table_sections:
            # Find position to insert separator (after headers)
            header_pos = 0
            for i, section in enumerate(table_sections):
                if any(header in section for header in headers):
                    header_pos = i
                    break
            
            if header_pos < len(table_sections) - 1:
                separator = "-" * len(table_sections[header_pos])
                table_sections.insert(header_pos + 1, separator)
        
        # Join table sections and add to main sections
        if table_sections:
            sections.append("\nTABLE START\n" + "\n".join(table_sections) + "\nTABLE END\n")
    
    # Find and process any financial data specially (often in specific divs or spans with classes)
    financial_elements = soup.find_all(['div', 'span'], class_=lambda c: c and any(keyword in c.lower() for keyword in ['financial', 'ekonomi', 'rapport', 'result', 'balans', 'finans']))
    
    for element in financial_elements:
        # Skip if this element is part of an already processed table
        if element.find_parent('table'):
            continue
            
        fin_text = ' '.join(element.stripped_strings)
        if fin_text and fin_text not in sections:
            sections.append(f"FINANCIAL DATA: {fin_text}")
    
    # Process any standalone spans that might contain important data
    standalone_spans = [span for span in soup.find_all('span') if not span.find_parent(['p', 'li', 'td', 'th', 'div'])]
    for span in standalone_spans:
        span_text = ' '.join(span.stripped_strings)
        if span_text and span_text not in sections:
            sections.append(span_text)
    
    # Join all sections with double newlines for better readability
    return '\n\n'.join(sections)

# Helper function to extract table as structured data
def extract_table_as_structured_data(table):
    """
    Extract a BeautifulSoup table element as structured data.
    
    Args:
        table: BeautifulSoup table element
        
    Returns:
        A list of dictionaries, where each dictionary represents a row
    """
    headers = []
    header_row = table.find('tr')
    if header_row:
        headers = [' '.join(th.stripped_strings) for th in header_row.find_all('th')]
    
    # If no th elements found, try first row as header
    if not headers and header_row:
        headers = [' '.join(td.stripped_strings) for td in header_row.find_all('td')]
    
    # Process data rows
    rows = []
    data_rows = table.find_all('tr')[1:] if headers else table.find_all('tr')
    
    for row in data_rows:
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
            
        # Create a row dictionary
        if headers:
            # Map to headers
            row_data = {}
            for i, cell in enumerate(cells):
                if i < len(headers):
                    row_data[headers[i]] = ' '.join(cell.stripped_strings)
                else:
                    # Handle extra cells
                    row_data[f'Column{i+1}'] = ' '.join(cell.stripped_strings)
            rows.append(row_data)
        else:
            # No headers, just collect values
            rows.append([' '.join(cell.stripped_strings) for cell in cells])
    
    return rows


# Create and save index using LlamaIndex, return the query engine
def create_llamaindex_query_engine(text, index_path):
    document = Document(text=text)
    index = VectorStoreIndex.from_documents([document])
    index.storage_context.persist(persist_dir=index_path)
    print(f"Index created and saved at {index_path}")
    return index.as_query_engine()

# Expose the query_annual_report function as an MCP tool
@mcp.tool()
def query_annual_report(org_no: str, year: int, query: str) -> str:
    """
    Ställ en fråga till en årsredovisning från Bolagsverket för en specifik organisation och år.
    
    Args:
        org_no: Organisationsnummer (t.ex. "5568925548")
        year: Året för årsredovisningen (t.ex. 2022)
        query: Frågan att ställa om årsredovisningen
        
    Returns:
        Svaret på frågan baserat på innehållet i årsredovisningen
    """
    xhtml_file_path = os.path.join(STORAGE_DIR, f"{org_no}_{year}.xhtml")
    index_path = os.path.join(STORAGE_DIR, f"{org_no}_{year}_index")
    
    # If the annual report exists, load its index, create a query engine and return the response
    if os.path.exists(xhtml_file_path):
        storage_context = StorageContext.from_defaults(persist_dir=index_path)
        index = load_index_from_storage(storage_context)
        print(f"Index loaded from {index_path}")
        query_engine = index.as_query_engine()
        response = query_engine.query(query+"Säkerställ att svaret är på svenska.")
        return str(response)
    else:
        print(f"Index for {org_no}_{year} not found, fetching annual report...")
        xhtml_file_path = fetch_annual_report(org_no, year)
        extracted_text = parse_xhtml(xhtml_file_path)
        query_engine = create_llamaindex_query_engine(extracted_text, index_path)
        response = query_engine.query(query)
        return str(response)

# Add an organization data tool
@mcp.tool()
def fetch_org_data(org_no: str) -> dict:
    """
    Hämta enklare, mer grundläggandeorganisationsdata från Bolagsverket för en specifik organisation.
    Exempelvis namn och adress.
    
    Args:
        org_no: Organisationsnummer (t.ex. "5568925548")
        
    Returns:
        Organisationsdata i JSON-format
    """
    return fetch_organisation_data(org_no)

@mcp.tool()
def get_org_no(company_name):
    """
    För att få ett organisationsnummer från ett organisationsnamn.

    Args:
        name: Organisationen eller bolagets namn (t.ex. "Gunnar Strandberg AB")
        
    Returns:
        Organisationens organisationsnummer, eller None om inget hittas.
    """
    # Create an instance of the search client with your API key.
    tavily_client = TavilyClient(api_key=os.getenv('TAVILY_API_KEY'))
    # Construct the query string.
    query = f"Vilket organisationsnummer har den svenska organisationen {company_name}?"
    
    try:
        results = tavily_client.search(query)
    except Exception as e:
        print("Error during Tavily search:", e)
        return None
    return results