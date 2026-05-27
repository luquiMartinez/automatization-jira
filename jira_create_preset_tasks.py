import sys
import re
import requests
from requests.auth import HTTPBasicAuth
import json
import warnings
import os

# Ocultar el warning molesto de urllib3 en macOS (NotOpenSSLWarning) sin importar urllib3 directamente
warnings.filterwarnings("ignore", message=".*NotOpenSSLWarning.*")
warnings.filterwarnings("ignore", category=UserWarning, module='urllib3')

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
if not os.path.exists(CONFIG_FILE):
    print(f"Error: No se encontró el archivo '{CONFIG_FILE}'.")
    sys.exit(1)

with open(CONFIG_FILE, 'r') as f:
    config = json.load(f)

API_TOKEN = config.get("API_TOKEN")
EMAIL = config.get("EMAIL")

if not API_TOKEN or not EMAIL:
    print(f"Error: El archivo '{CONFIG_FILE}' debe contener 'EMAIL' y 'API_TOKEN'.")
    sys.exit(1)

# Tareas predefinidas con sus mapeos a padres
PRESET_TASKS = [
    {"template": "REUI - {project_name}", "parent_type": "BILLABLE"},
    {"template": "GG - {project_name}", "parent_type": "BILLABLE"},
    {"template": "REUE - {project_name}", "parent_type": "BILLABLE"},
    {"template": "AM - {project_name} - NB", "parent_type": "NON_BILLABLE"}
]

def parse_jira_context(url):
    """Extrae project key y, si la URL es de un tablero, el board id."""
    match = re.search(r'/projects/([^/]+)', url)
    if not match:
        raise ValueError("URL inválida. No se pudo encontrar el Project Key.")
    project_key = match.group(1).split('/')[0]
    board_match = re.search(r'/boards/(\d+)', url)
    board_id = board_match.group(1) if board_match else None
    return project_key, board_id


def normalize_label_for_templates(display_name):
    """
    Si el nombre en Jira ya lleva prefijo REUI/GG/REUE/AM, quítalo para no duplicarlo
    en las plantillas (ej. tablero 'REUE - BBVA - ...' -> sufijo para 'REUE - BBVA - ...').
    """
    if not display_name:
        return display_name
    s = display_name.strip()
    m = re.match(r"^(?i)(REUI|GG|REUE|AM)\s*-\s*(.+)$", s)
    return m.group(2).strip() if m else s


def fetch_display_name_for_summaries(domain, project_key, board_id, auth):
    """
    Nombre para {project_name}: tablero (si la URL incluye board id) o nombre del proyecto.
    """
    headers = {"Accept": "application/json"}
    if board_id:
        board_url = f"{domain}/rest/agile/1.0/board/{board_id}"
        res = requests.get(board_url, auth=auth, headers=headers)
        if res.status_code == 200:
            name = (res.json() or {}).get("name")
            if name and str(name).strip():
                return normalize_label_for_templates(str(name).strip())
        print(f"  [Aviso] No se pudo leer el tablero {board_id} ({res.status_code}). Probando nombre del proyecto...")
    proj_url = f"{domain}/rest/api/3/project/{project_key}"
    res = requests.get(proj_url, auth=auth, headers=headers)
    if res.status_code == 200:
        name = (res.json() or {}).get("name")
        if name and str(name).strip():
            return normalize_label_for_templates(str(name).strip())
    print(f"  [Aviso] No se pudo leer el proyecto {project_key} ({res.status_code}).")
    return None

def create_subtask(domain, project_key, parent_key, summary, auth):
    url = f"{domain}/rest/api/3/issue"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "fields": {
            "project": {"key": project_key},
            "parent": {"key": parent_key},
            "summary": summary,
            "issuetype": {"name": "Sub-task"}
        }
    }
    
    res = requests.post(url, json=payload, auth=auth, headers=headers)
    return res

def main():
    if len(sys.argv) < 4:
        print("Uso: python jira_create_preset_tasks.py <URL_PROYECTO_O_TABLERO> <BILLABLE_PARENT_KEY> <NON_BILLABLE_PARENT_KEY>")
        print('Ejemplo: python jira_create_preset_tasks.py "https://.../projects/MIPROJ" "MIPROJ-14" "MIPROJ-1"')
        print('  Los títulos usan el nombre del proyecto en Jira (API). Si la URL incluye /boards/ID, se usa el nombre del tablero.')
        sys.exit(1)
        
    url_input = sys.argv[1]
    billable_parent = sys.argv[2]
    non_billable_parent = sys.argv[3]
    
    domain = "/".join(url_input.split("/")[:3])
    
    try:
        project_key, board_id = parse_jira_context(url_input)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    auth = HTTPBasicAuth(EMAIL, API_TOKEN)
    name_for_summaries = fetch_display_name_for_summaries(domain, project_key, board_id, auth)
    if not name_for_summaries:
        name_for_summaries = project_key
        print(f"  [Aviso] Usando la clave del proyecto en los títulos: {project_key}")

    print(f"=== Creando Sub-tareas de Set Up (Child Items) ===")
    print(f"Proyecto (clave Jira): {project_key}")
    if board_id:
        print(f"Tablero en URL: {board_id} (nombre tomado del tablero si fue posible)")
    print(f"Nombre en títulos: {name_for_summaries}")
    print(f"Billiable Parent: {billable_parent}")
    print(f"No Billiable Parent: {non_billable_parent}")
    print("-" * 50)
    
    success_count = 0
    for task in PRESET_TASKS:
        summary = task["template"].format(project_name=name_for_summaries)
        
        # Resolver el padre
        if task["parent_type"] == "BILLABLE":
            parent_key = billable_parent
        else:
            parent_key = non_billable_parent

        print(f"Creando: {summary} (Hijo de {parent_key})...")
        res = create_subtask(domain, project_key, parent_key, summary, auth)
        
        if res.status_code == 201:
            issue_key = res.json().get('key')
            print(f"  [OK] Creada con éxito: {issue_key}")
            success_count += 1
        else:
            print(f"  [ERROR] No se pudo crear: {res.status_code}")
            print(f"  Detalle: {res.text}")

    print("-" * 50)
    print(f"¡Proceso finalizado! Se crearon {success_count} de {len(PRESET_TASKS)} sub-tareas.")

if __name__ == "__main__":
    main()
