import sys
import re
import requests
from requests.auth import HTTPBasicAuth
import json
import warnings
import os

# Ocultar warnings molestos de urllib3 en macOS sin importar urllib3 directamente
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
DOMAIN = config.get("DOMAIN", "https://ddm-monks.atlassian.net").rstrip('/')

if not API_TOKEN or not EMAIL:
    print(f"Error: El archivo '{CONFIG_FILE}' debe contener 'EMAIL' y 'API_TOKEN'.")
    sys.exit(1)

def get_issue(issue_key, auth):
    url = f"{DOMAIN}/rest/api/3/issue/{issue_key}"
    headers = {"Accept": "application/json"}
    res = requests.get(url, auth=auth, headers=headers)
    if res.status_code == 404:
        raise ValueError(f"La tarea origen '{issue_key}' no existe o no tienes permisos para verla.")
    res.raise_for_status()
    return res.json()

def create_issue(project_key, summary, description, issue_type_name, parent_key, auth):
    url = f"{DOMAIN}/rest/api/3/issue"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # Manejar sub-tareas sin padre definido
    if (issue_type_name.lower() in ("sub-task", "subtarea", "sub-tarea")) and not parent_key:
        print(f"  [Info] La tarea original es una sub-tarea pero no especificaste un Padre en el proyecto destino.")
        print(f"         Se intentará crear como 'Task' estándar...")
        issue_type_name = "Task"

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type_name}
        }
    }
    
    if parent_key:
        payload["fields"]["parent"] = {"key": parent_key}
        
    if description:
        payload["fields"]["description"] = description

    res = requests.post(url, json=payload, auth=auth, headers=headers)
    
    if res.status_code != 201:
        res_text = res.text
        # Si falta el Parent y no lo enviamos
        if "Parent" in res_text and not parent_key:
            raise ValueError(
                "Jira requiere especificar un Padre (Epic o Tarea superior) para crear tareas en este proyecto.\n"
                "  Por favor, ejecuta el script agregando la Key del padre como tercer parámetro:\n"
                f"  python3 jira_migrate_task.py {sys.argv[1]} {project_key} <KEY_PADRE_NUEVO>"
            )
        # Si falla por tipo de issue inválido y no era Task, reintentar usando "Task"
        if issue_type_name.lower() != "task" and ("issuetype" in res_text or "issue type" in res_text.lower()):
            print(f"  [Advertencia] No se pudo crear con el tipo '{issue_type_name}'. Reintentando con tipo 'Task'...")
            payload["fields"]["issuetype"] = {"name": "Task"}
            res = requests.post(url, json=payload, auth=auth, headers=headers)
            
    res.raise_for_status()
    return res.json()

def link_issues(inward_key, outward_key, auth):
    url = f"{DOMAIN}/rest/api/3/issueLink"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "type": {
            "name": "Relates"
        },
        "inwardIssue": {
            "key": inward_key
        },
        "outwardIssue": {
            "key": outward_key
        }
    }
    
    res = requests.post(url, json=payload, auth=auth, headers=headers)
    if res.status_code not in (200, 201, 204):
        print(f"  [Advertencia] No se pudo crear el enlace nativo de Jira (status: {res.status_code}).")
        print(f"  Detalle del error de enlace: {res.text}")
    else:
        print("  [OK] Enlace nativo creado con éxito entre ambas tareas.")

def add_comment(issue_key, message_text, target_key, target_url, auth):
    url = f"{DOMAIN}/rest/api/3/issue/{issue_key}/comment"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # ADF JSON format for structured link comments
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": message_text
                        },
                        {
                            "type": "text",
                            "text": target_key,
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {
                                        "href": target_url,
                                        "title": f"Tarea {target_key}"
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    }
    
    res = requests.post(url, json=payload, auth=auth, headers=headers)
    if res.status_code == 201:
        print(f"  [OK] Comentario añadido con éxito en {issue_key}.")
    else:
        print(f"  [Advertencia] No se pudo añadir el comentario en {issue_key} (status: {res.status_code}).")

def main():
    if len(sys.argv) < 3:
        print("Uso: python3 jira_migrate_task.py <KEY_TAREA_VIEJA> <KEY_PROYECTO_NUEVO> [KEY_PADRE_NUEVO]")
        print("Ejemplo: python3 jira_migrate_task.py \"E00033336-14\" \"INTDATALB\"")
        print("Ejemplo con Padre: python3 jira_migrate_task.py \"INTDATALB-352\" \"INTDATALB\" \"INTDATALB-13\"")
        sys.exit(1)
        
    old_issue_key = sys.argv[1].upper().strip()
    new_project_key = sys.argv[2].upper().strip()
    new_parent_key = sys.argv[3].upper().strip() if len(sys.argv) > 3 else None
    
    print(f"=== Iniciando Migración de Tarea ===")
    print(f"Tarea vieja (origen): {old_issue_key}")
    print(f"Proyecto nuevo (destino): {new_project_key}")
    if new_parent_key:
        print(f"Padre nuevo (destino): {new_parent_key}")
    print(f"Dominio Jira: {DOMAIN}")
    print("-" * 50)
    
    auth = HTTPBasicAuth(EMAIL, API_TOKEN)
    
    try:
        # 1. Obtener detalles de la tarea vieja
        print("Obteniendo detalles de la tarea origen...")
        old_issue = get_issue(old_issue_key, auth)
        fields = old_issue.get("fields", {})
        
        summary = fields.get("summary")
        description = fields.get("description")
        issue_type = fields.get("issuetype", {})
        issue_type_name = issue_type.get("name", "Task")
        old_parent = fields.get("parent", {})
        
        print(f"  [OK] Detalles obtenidos: '{summary}' (Tipo: {issue_type_name})")
        if old_parent and not new_parent_key:
            print(f"  [Info] La tarea origen pertenece al padre: {old_parent.get('key')} ({old_parent.get('fields', {}).get('summary')})")
            print(f"         Si deseas asignarle un padre en el nuevo proyecto, recuerda pasar su Key como 3er parámetro.")
        
        # 2. Crear la nueva tarea en el nuevo proyecto
        print("\nCreando la nueva tarea en el proyecto destino...")
        new_issue = create_issue(new_project_key, summary, description, issue_type_name, new_parent_key, auth)
        new_issue_key = new_issue.get("key")
        
        new_url = f"{DOMAIN}/browse/{new_issue_key}"
        old_url = f"{DOMAIN}/browse/{old_issue_key}"
        
        print(f"  [OK] Nueva tarea creada: {new_issue_key} ({new_url})")
        
        # 3. Vincular ambas tareas de manera nativa
        print("\nVinculando tareas de manera nativa...")
        link_issues(old_issue_key, new_issue_key, auth)
        
        # 4. Añadir comentarios de trazabilidad
        print("\nAñadiendo comentarios de trazabilidad...")
        
        # Comentario en la tarea nueva
        add_comment(
            issue_key=new_issue_key,
            message_text="Migrada desde la tarea original: ",
            target_key=old_issue_key,
            target_url=old_url,
            auth=auth
        )
        
        # Comentario en la tarea vieja
        add_comment(
            issue_key=old_issue_key,
            message_text="Esta tarea ha sido migrada al nuevo proyecto. Nueva tarea: ",
            target_key=new_issue_key,
            target_url=new_url,
            auth=auth
        )
        
        print("-" * 50)
        print(f"¡Migración completada con éxito! 🎉")
        print(f"Nueva tarea: {new_issue_key}")
        
    except requests.exceptions.RequestException as e:
        print(f"\n[ERROR] Hubo un problema al comunicarse con la API de Jira: {e}")
        if e.response is not None:
            print(f"Detalles del error: {e.response.text}")
        sys.exit(1)
    except ValueError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
