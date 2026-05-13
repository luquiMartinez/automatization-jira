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

# Tareas predefinidas para el set up inicial
PRESET_TASKS = [
    {"summary": "Setup: Configuración de Tablero y Columnas", "description": "Ejecutar el script de estandarización de columnas y verificar el flujo de trabajo."},
    {"summary": "Setup: Mapeo Inicial de Status", "description": "Revisar que todos los status del workflow estén correctamente asignados a las columnas del tablero."},
    {"summary": "Setup: Definición de Filtros de Visualización", "description": "Configurar los filtros necesarios para ocultar tareas técnicas o irrelevantes del tablero principal."},
    {"summary": "Setup: Kick-off Técnico del Proyecto", "description": "Reunión inicial para alinear al equipo con la nueva estructura del tablero de Jira."}
]

def parse_url(url):
    # Intentar extraer el project key de URLs de tablero o de proyecto
    match = re.search(r'/projects/([^/]+)', url)
    if not match:
        raise ValueError("URL inválida. No se pudo encontrar el Project Key.")
    return match.group(1).split('/')[0]

def create_issue(domain, project_key, summary, description, auth):
    url = f"{domain}/rest/api/3/issue"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # Estructura básica para Jira Cloud API v3 (ADF para descripción)
    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": description
                            }
                        ]
                    }
                ]
            },
            "issuetype": {"name": "Task"} # Asumimos que existe el tipo "Task"
        }
    }
    
    res = requests.post(url, json=payload, auth=auth, headers=headers)
    return res

def main():
    if len(sys.argv) < 2:
        print("Uso: python jira_create_preset_tasks.py <PROJECT_OR_BOARD_URL>")
        sys.exit(1)
        
    url_input = sys.argv[1]
    domain = "/".join(url_input.split("/")[:3]) # Extrae https://dominio.atlassian.net
    
    try:
        project_key = parse_url(url_input)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"=== Creando Tareas de Set Up Inicial ===")
    print(f"Proyecto: {project_key}")
    print("-" * 40)
    
    auth = HTTPBasicAuth(EMAIL, API_TOKEN)
    
    success_count = 0
    for task in PRESET_TASKS:
        print(f"Creando: {task['summary']}...")
        res = create_issue(domain, project_key, task['summary'], task['description'], auth)
        
        if res.status_code == 201:
            issue_key = res.json().get('key')
            print(f"  [OK] Creada con éxito: {issue_key}")
            success_count += 1
        else:
            print(f"  [ERROR] No se pudo crear: {res.status_code}")
            print(f"  Detalle: {res.text}")

    print("-" * 40)
    print(f"¡Proceso finalizado! Se crearon {success_count} de {len(PRESET_TASKS)} tareas.")

if __name__ == "__main__":
    main()
