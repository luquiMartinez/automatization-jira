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

def parse_url(url):
    match = re.search(r'(https?://[^/]+).*?/projects/([^/]+)/boards/(\d+)', url)
    if not match:
        raise ValueError("URL inválida. Asegúrate de copiar el link del tablero de Jira.")
    return match.group(1), match.group(2), match.group(3)

def get_board_filter_id(domain, board_id, auth):
    url = f"{domain}/rest/greenhopper/1.0/rapidviewconfig/editmodel.json?rapidViewId={board_id}"
    res = requests.get(url, auth=auth)
    res.raise_for_status()
    data = res.json()
    filter_id = data.get('filterConfig', {}).get('id')
    if not filter_id:
        raise ValueError("No se pudo encontrar el ID del filtro asociado a este tablero.")
    return filter_id

def get_filter(domain, filter_id, auth):
    url = f"{domain}/rest/api/3/filter/{filter_id}"
    res = requests.get(url, auth=auth, headers={"Accept": "application/json"})
    res.raise_for_status()
    return res.json()

def update_filter(domain, filter_id, filter_data, new_jql, auth):
    url = f"{domain}/rest/api/3/filter/{filter_id}"
    payload = {
        "name": filter_data['name'],
        "jql": new_jql
    }
    if 'description' in filter_data and filter_data['description']:
        payload['description'] = filter_data['description']
        
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    res = requests.put(url, auth=auth, json=payload, headers=headers)
    res.raise_for_status()
    return res.json()

def modify_jql(original_jql, base_key, numbers_to_hide):
    # 1. Generar la lista de nuevas keys
    new_keys = [f"{base_key}-{num.strip()}" for num in numbers_to_hide.split(',') if num.strip()]
    
    # 2. Buscar si ya hay cláusulas 'issuekey NOT IN (...)' usando Regex
    pattern = re.compile(r'(?:\s+and\s+)?issuekey\s+not\s+in\s*\(([^)]+)\)', re.IGNORECASE)
    
    existing_keys = set()
    for match in pattern.finditer(original_jql):
        keys_str = match.group(1)
        # Limpiar comillas y espacios de las keys existentes
        keys = [k.strip().strip("'").strip('"') for k in keys_str.split(',')]
        existing_keys.update(keys)
        
    # Unir todas las keys (existentes + nuevas)
    all_keys = existing_keys.union(new_keys)
    
    if not all_keys:
        return original_jql
        
    # 3. Remover las cláusulas antiguas del JQL
    cleaned_jql = pattern.sub('', original_jql).strip()
    
    # Limpiar si quedó algún 'AND' suelto al final por error del regex
    if cleaned_jql.upper().endswith(' AND'):
        cleaned_jql = cleaned_jql[:-4].strip()
        
    # 4. Inyectar la nueva cláusula unificada
    keys_formatted = ', '.join(sorted(all_keys))
    new_clause = f"AND issuekey NOT IN ({keys_formatted})"
    
    # Buscar si hay un 'ORDER BY'
    order_match = re.search(r'\s+ORDER\s+BY\s+.*', cleaned_jql, re.IGNORECASE)
    if order_match:
        before_order = cleaned_jql[:order_match.start()].strip()
        order_clause = order_match.group(0).strip()
        
        if not before_order:
            # Caso raro: Solo había 'issuekey NOT IN' y luego el ORDER BY
            final_jql = f"{new_clause.replace('AND ', '', 1)} {order_clause}"
        else:
            final_jql = f"{before_order} {new_clause} {order_clause}"
    else:
        if not cleaned_jql:
            final_jql = new_clause.replace('AND ', '', 1)
        else:
            final_jql = f"{cleaned_jql} {new_clause}"
        
    return final_jql

def main():
    if len(sys.argv) < 4:
        print('Uso: python jira_hide_tasks.py "URL_DEL_TABLERO" "BASE_KEY" "1,2,3"')
        print('Ejemplo: python jira_hide_tasks.py "https://ddm-monks.atlassian.net/.../boards/60" "E00033340" "2,3,4,5"')
        sys.exit(1)
        
    url = sys.argv[1]
    base_key = sys.argv[2]
    if base_key.endswith('-'):
        base_key = base_key[:-1]
    numbers_str = sys.argv[3]
    
    try:
        domain, project_key, board_id = parse_url(url)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(f"=== Ocultando Tareas en Tablero ===")
    print(f"Proyecto: {project_key} | Board ID: {board_id}")
    print(f"Tareas a ocultar de {base_key}: {numbers_str}")
    print("-" * 40)
    
    auth = HTTPBasicAuth(EMAIL, API_TOKEN)
    
    try:
        print("Obteniendo ID del filtro del tablero...")
        filter_id = get_board_filter_id(domain, board_id, auth)
        
        print(f"Filtro encontrado (ID: {filter_id}). Leyendo configuración...")
        filter_data = get_filter(domain, filter_id, auth)
        original_jql = filter_data.get('jql', '')
        
        print("\n[JQL Original]")
        print(original_jql)
        
        final_jql = modify_jql(original_jql, base_key, numbers_str)
        
        print("\n[JQL Modificado]")
        print(final_jql)
        
        print("\nGuardando nueva configuración de filtro en Jira...")
        update_filter(domain, filter_id, filter_data, final_jql, auth)
        print("¡Filtro actualizado con éxito! Las tareas han sido ocultadas. 🎉")
        
    except requests.exceptions.RequestException as e:
        print(f"Error en la API de Jira: {e}")
        if e.response is not None:
            print(f"Detalle: {e.response.text}")
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
