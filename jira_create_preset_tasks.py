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

def parse_url(url):
    # Extraer el project key de la URL
    match = re.search(r'/projects/([^/]+)', url)
    if not match:
        raise ValueError("URL inválida. No se pudo encontrar el Project Key.")
    return match.group(1).split('/')[0]

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
        print("Uso: python jira_create_preset_tasks.py <URL_PROYECTO> <BILLABLE_PARENT_KEY> <NON_BILLABLE_PARENT_KEY>")
        print('Ejemplo: python jira_create_preset_tasks.py "https://..." "PROJ-14" "PROJ-1"')
        sys.exit(1)
        
    url_input = sys.argv[1]
    billable_parent = sys.argv[2]
    non_billable_parent = sys.argv[3]
    
    domain = "/".join(url_input.split("/")[:3])
    
    try:
        project_key = parse_url(url_input)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"=== Creando Sub-tareas de Set Up (Child Items) ===")
    print(f"Proyecto: {project_key}")
    print(f"Billiable Parent: {billable_parent}")
    print(f"No Billiable Parent: {non_billable_parent}")
    print("-" * 50)
    
    auth = HTTPBasicAuth(EMAIL, API_TOKEN)
    
    success_count = 0
    for task in PRESET_TASKS:
        # Resolver el nombre del proyecto (usamos el key del proyecto)
        summary = task["template"].format(project_name=project_key)
        
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
