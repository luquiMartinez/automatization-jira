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

# Plantilla estándar de columnas requerida para todos los proyectos
TARGET_COLUMNS = [
    "NOT STARTED",
    "ESTIMATE",
    "TO DO",
    "IN PROGRESS",
    "IN REVIEW",
    "IN UAT",
    "DEPLOY",
    "DONE",
    "CANCELLED",
    "BLOCKED"
]

# Sinónimos para emparejar automáticamente status que se llamen distinto
SYNONYMS = {
    "COMPLETED": "DONE",
    "BACKLOG": "NOT STARTED"
}

def parse_url(url):
    match = re.search(r'(https?://[^/]+).*?/projects/([^/]+)/boards/(\d+)', url)
    if not match:
        raise ValueError("URL inválida. Asegúrate de copiarla desde tu navegador cuando estás en el tablero.")
    return match.group(1), match.group(2), match.group(3)

def get_project_statuses(domain, project_key, auth):
    url = f"{domain}/rest/api/3/project/{project_key}/statuses"
    res = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    res.raise_for_status()
    statuses = {}
    for issue_type in res.json():
        for status in issue_type.get('statuses', []):
            statuses[status['id']] = status['name']
    return statuses

def get_board_config(domain, board_id, auth):
    url = f"{domain}/rest/greenhopper/1.0/rapidviewconfig/editmodel.json?rapidViewId={board_id}"
    res = requests.get(url, auth=auth)
    res.raise_for_status()
    return res.json()

def map_status_to_column(status_name):
    upper_name = status_name.upper().strip()
    if upper_name in TARGET_COLUMNS:
        return upper_name
    if upper_name in SYNONYMS:
        return SYNONYMS[upper_name]
    return None

def main():
    if len(sys.argv) < 2:
        print("Uso: python jira_workflow_automator.py <JIRA_BOARD_URL>")
        sys.exit(1)
        
    url = sys.argv[1]
    
    try:
        domain, project_key, board_id = parse_url(url)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"=== Estandarizando Tablero Kanban ===")
    print(f"Proyecto: {project_key}")
    print(f"Board ID: {board_id}")
    print("-" * 37)
    
    auth = HTTPBasicAuth(EMAIL, API_TOKEN)
    
    try:
        project_statuses = get_project_statuses(domain, project_key, auth)
        board_config = get_board_config(domain, board_id, auth)
    except requests.exceptions.RequestException as e:
        print(f"Error conectando a Jira: {e}")
        sys.exit(1)
    
    # Preparar el nuevo layout de columnas con la plantilla estricta
    new_columns = []
    
    # Columna obligatoria oculta para el Kanban Backlog de Jira
    # Si no la ponemos, Jira secuestra la primera columna ("NOT STARTED")
    kanban_backlog_col = {
        "name": "Backlog",
        "isKanPlanColumn": True,
        "mappedStatuses": []
    }
    
    existing_columns = board_config.get('rapidListConfig', {}).get('mappedColumns', [])
    existing_col_map = {col['name'].upper(): col.get('id') for col in existing_columns}

    # Si ya existía un ID para Backlog, lo reusamos
    if "BACKLOG" in existing_col_map:
        kanban_backlog_col["id"] = existing_col_map["BACKLOG"]
        
    new_columns.append(kanban_backlog_col)

    for col_name in TARGET_COLUMNS:
        col = {
            "name": col_name,
            "mappedStatuses": [],
            "isKanPlanColumn": False
        }
            
        # Reutilizar el ID si la columna ya existía
        if col_name.upper() in existing_col_map:
            col["id"] = existing_col_map[col_name.upper()]
            
        new_columns.append(col)
        
    col_dict = {col["name"]: col for col in new_columns}
    unmapped_alerts = []

    print("Analizando y asignando status...")
    for status_id, status_name in project_statuses.items():
        target_col = map_status_to_column(status_name)
        if target_col:
            col_dict[target_col]["mappedStatuses"].append({"id": status_id})
            print(f"  [OK] '{status_name}' -> asignado a columna '{target_col}'")
        else:
            unmapped_alerts.append(f"  - '{status_name}' (ID: {status_id})")

    # Armar payload para enviar por la API
    payload = {
        "rapidViewId": int(board_id),
        "mappedColumns": new_columns
    }
    
    put_url = f"{domain}/rest/greenhopper/1.0/rapidviewconfig/columns"
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    
    print("\nEnviando nueva configuración a Jira...")
    res = requests.put(put_url, auth=auth, json=payload, headers=headers)
    
    if res.status_code == 200:
        print("¡Tablero estandarizado con éxito! 🎉")
    else:
        print(f"Error al actualizar tablero: {res.status_code}")
        print(res.text)
        
    if unmapped_alerts:
        print("\n=== ATENCIÓN: STATUS NO RECONOCIDOS ===")
        print("Los siguientes status no coincidieron con ninguna columna de la plantilla y quedaron sueltos (Unmapped):")
        for alert in unmapped_alerts:
            print(alert)
        print("Puedes asignarlos manualmente en Jira o añadirlos a los SYNONYMS del script.")

if __name__ == "__main__":
    main()
