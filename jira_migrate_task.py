import sys
import re
import requests
from requests.auth import HTTPBasicAuth
import json
import copy
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

def classify_parent_summary(summary):
    summary_lower = summary.lower()
    # Buscar patrones para Non-Billable / NB
    if "non-billable" in summary_lower or "non billable" in summary_lower or re.search(r'\bnb\b', summary_lower):
        return "NON_BILLABLE"
    # Buscar patrones para Billable / Billiable
    if "billable" in summary_lower or "billiable" in summary_lower:
        return "BILLABLE"
    return None

def find_equivalent_parent(project_key, old_parent_summary, auth):
    parent_type = classify_parent_summary(old_parent_summary)
    
    if parent_type == "BILLABLE":
        jql = f'project = "{project_key}" AND (summary ~ "billable" OR summary ~ "billiable")'
        print(f"  [Auto-Parent] Tarea origen clasificada como 'BILLABLE'. Buscando equivalente en '{project_key}'...")
    elif parent_type == "NON_BILLABLE":
        jql = f'project = "{project_key}" AND (summary ~ "nb" OR summary ~ "non-billable" OR summary ~ "non billable")'
        print(f"  [Auto-Parent] Tarea origen clasificada como 'NON-BILLABLE'. Buscando equivalente en '{project_key}'...")
    else:
        escaped_summary = old_parent_summary.replace('"', '\\"')
        jql = f'project = "{project_key}" AND summary ~ "{escaped_summary}"'
        print(f"  [Auto-Parent] Buscando tarea con título exacto en '{project_key}'...")

    url = f"{DOMAIN}/rest/api/3/search/jql"
    params = {
        "jql": jql,
        "fields": "summary",
        "maxResults": 30
    }
    
    headers = {"Accept": "application/json"}
    try:
        res = requests.get(url, auth=auth, headers=headers, params=params)
        if res.status_code != 200:
            return None
        
        issues = res.json().get("issues", [])
        
        if parent_type == "BILLABLE":
            for issue in issues:
                summary = issue.get("fields", {}).get("summary", "").lower()
                if "billable" in summary or "billiable" in summary:
                    return issue.get("key")
        elif parent_type == "NON_BILLABLE":
            for issue in issues:
                summary = issue.get("fields", {}).get("summary", "").lower()
                if "non-billable" in summary or "non billable" in summary or re.search(r'\bnb\b', summary):
                    return issue.get("key")
        else:
            # Fallback exact match
            target_summary_clean = old_parent_summary.strip().lower()
            for issue in issues:
                summary = issue.get("fields", {}).get("summary", "").lower().strip()
                if summary == target_summary_clean:
                    return issue.get("key")
    except Exception as e:
        print(f"  [Advertencia] Error al buscar padre equivalente: {e}")
    return None


# Nodos ADF que suelen provocar 400 al crear issues (adjuntos/medios que no existen en el destino).
_UNSAFE_ADF_TYPES = frozenset(
    {"media", "mediaSingle", "mediaGroup", "embedCard", "blockCard"}
)
# Bloques que Jira no admite vacíos tras quitar hijos.
_ADF_EMPTY_INVALID = frozenset(
    {
        "paragraph",
        "heading",
        "blockquote",
        "bulletList",
        "orderedList",
        "listItem",
        "table",
        "tableRow",
        "tableHeader",
        "tableCell",
        "expand",
        "panel",
        "codeBlock",
    }
)


def _sanitize_adf_tree(node, tracker):
    """Quita nodos problemáticos in-place. tracker['unsafe_removed'] indica si se eliminó algún nodo de tipo inseguro."""
    if not isinstance(node, dict):
        return True
    if node.get("type") in _UNSAFE_ADF_TYPES:
        tracker["unsafe_removed"] = True
        return False
    if "content" in node and isinstance(node["content"], list):
        kept = []
        for ch in node["content"]:
            if not isinstance(ch, dict):
                kept.append(ch)
                continue
            if ch.get("type") in _UNSAFE_ADF_TYPES:
                tracker["unsafe_removed"] = True
                continue
            if not _sanitize_adf_tree(ch, tracker):
                continue
            kept.append(ch)
        node["content"] = kept
        t = node.get("type")
        if not kept and t in _ADF_EMPTY_INVALID:
            return False
    return True


def sanitize_adf_description(description):
    """
    Devuelve (adf_seguro | mismo valor | None, hubo_eliminaciones_inseguras).
    Para documentos doc, el segundo elemento es True si se quitó media/embed/blockCard, etc.
    """
    if not description or not isinstance(description, dict):
        return description, False
    if description.get("type") != "doc":
        return description, False
    tracker = {"unsafe_removed": False}
    doc = copy.deepcopy(description)
    _sanitize_adf_tree(doc, tracker)
    if not doc.get("content"):
        return None, tracker["unsafe_removed"]
    return doc, tracker["unsafe_removed"]


def build_sanitized_migration_notice_paragraph():
    """Párrafo inicial cuando se eliminaron adjuntos/medios del ADF al migrar."""
    return {
        "type": "paragraph",
        "content": [
            {
                "type": "text",
                "text": "Aviso: ",
                "marks": [{"type": "strong"}],
            },
            {
                "type": "text",
                "text": (
                    "La tarea original incluye archivos adjuntos o medios incrustados que no se migraron "
                    "automáticamente por API. A continuación, el resto de la descripción que sí se pudo copiar."
                ),
            },
        ],
    }


def prepend_paragraph_to_adf_doc(doc, paragraph):
    """Inserta un bloque párrafo al inicio de un documento ADF tipo doc."""
    if not doc or doc.get("type") != "doc":
        return doc
    body = list(doc.get("content") or [])
    doc["content"] = [paragraph] + body
    return doc


def build_description_redirect_adf(original_key, original_url):
    """Descripción mínima en ADF que redirige a la tarea origen (sin adjuntos ni medios)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Descripción en la tarea original: ",
                    },
                    {
                        "type": "text",
                        "text": original_key,
                        "marks": [
                            {
                                "type": "link",
                                "attrs": {
                                    "href": original_url,
                                    "title": f"Tarea {original_key}",
                                },
                            }
                        ],
                    },
                    {"type": "text", "text": " (incluye texto, adjuntos y medios incrustados)."},
                ],
            }
        ],
    }


def create_issue(project_key, summary, description, issue_type_name, parent_key, auth, source_issue_key=None):
    url = f"{DOMAIN}/rest/api/3/issue"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # Manejar sub-tareas sin padre definido
    if (issue_type_name.lower() in ("sub-task", "subtarea", "sub-tarea")) and not parent_key:
        print(f"  [Info] La tarea original es una sub-tarea pero no se pudo encontrar o definir un Padre en el destino.")
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

    original_url = f"{DOMAIN}/browse/{source_issue_key}" if source_issue_key else None
    had_original_description = description not in (None, "", {})

    desc_sanitized = None
    stripped_unsafe_from_adf = False
    if description:
        desc_sanitized, stripped_unsafe_from_adf = sanitize_adf_description(description)
        if isinstance(desc_sanitized, dict) and desc_sanitized.get("type") == "doc" and stripped_unsafe_from_adf:
            desc_sanitized = prepend_paragraph_to_adf_doc(
                desc_sanitized, build_sanitized_migration_notice_paragraph()
            )

    if desc_sanitized:
        payload["fields"]["description"] = desc_sanitized
    elif had_original_description and source_issue_key:
        payload["fields"]["description"] = build_description_redirect_adf(source_issue_key, original_url)

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

    if res.status_code != 201:
        try:
            err_json = res.json()
        except Exception:
            err_json = {}
        desc_err = (err_json.get("errors") or {}).get("description")
        if res.status_code == 400 and desc_err and "description" in payload["fields"] and source_issue_key:
            print(
                "  [Aviso] Jira rechazó la descripción migrada (p. ej. adjuntos o formato no clonable). "
                "Se usará una descripción breve con enlace a la tarea original."
            )
            payload_retry = copy.deepcopy(payload)
            payload_retry["fields"]["description"] = build_description_redirect_adf(source_issue_key, original_url)
            res = requests.post(url, json=payload_retry, auth=auth, headers=headers)

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


def parse_old_issue_keys_csv(first_arg):
    """Varias claves separadas por comas (espacios opcionales). Una sola clave sigue siendo válida."""
    return [p.strip().upper() for p in first_arg.split(",") if p.strip()]


def migrate_one_issue(old_issue_key, new_project_key, new_parent_key, auth):
    """
    Migra una tarea origen al proyecto destino. Lanza requests.RequestException o ValueError en error.
    """
    print("Obteniendo detalles de la tarea origen...")
    old_issue = get_issue(old_issue_key, auth)
    fields = old_issue.get("fields", {})

    summary = fields.get("summary")
    description = fields.get("description")
    issue_type = fields.get("issuetype", {})
    issue_type_name = issue_type.get("name", "Task")
    old_parent = fields.get("parent", {})

    print(f"  [OK] Detalles obtenidos: '{summary}' (Tipo: {issue_type_name})")

    parent_key_to_use = new_parent_key

    if old_parent:
        old_parent_key = old_parent.get("key")
        old_parent_fields = old_parent.get("fields", {})
        old_parent_summary = old_parent_fields.get("summary")

        print(f"  [Info] La tarea origen pertenece al padre: {old_parent_key} (\"{old_parent_summary}\")")

        if not parent_key_to_use:
            parent_key_to_use = find_equivalent_parent(new_project_key, old_parent_summary, auth)
            if parent_key_to_use:
                print(f"  [Auto-Parent] ¡Padre asignado automáticamente!: {parent_key_to_use}")
            else:
                print(
                    f"  [Auto-Parent] No se pudo encontrar un padre equivalente 'BILLABLE' o 'NON-BILLABLE' en '{new_project_key}'."
                )
        else:
            print(f"  [Info] Se utilizará el padre especificado por parámetro: {parent_key_to_use}")

    print("\nCreando la nueva tarea en el proyecto destino...")
    new_issue = create_issue(
        new_project_key,
        summary,
        description,
        issue_type_name,
        parent_key_to_use,
        auth,
        source_issue_key=old_issue_key,
    )
    new_issue_key = new_issue.get("key")

    new_url = f"{DOMAIN}/browse/{new_issue_key}"
    old_url = f"{DOMAIN}/browse/{old_issue_key}"

    print(f"  [OK] Nueva tarea creada: {new_issue_key} ({new_url})")

    print("\nVinculando tareas de manera nativa...")
    link_issues(old_issue_key, new_issue_key, auth)

    print("\nAñadiendo comentarios de trazabilidad...")

    add_comment(
        issue_key=new_issue_key,
        message_text="Migrada desde la tarea original: ",
        target_key=old_issue_key,
        target_url=old_url,
        auth=auth,
    )

    add_comment(
        issue_key=old_issue_key,
        message_text="Esta tarea ha sido migrada al nuevo proyecto. Nueva tarea: ",
        target_key=new_issue_key,
        target_url=new_url,
        auth=auth,
    )

    print("-" * 50)
    print("¡Migración completada con éxito! 🎉")
    print(f"Nueva tarea: {new_issue_key}")
    return new_issue_key


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 jira_migrate_task.py <KEY(S)_TAREA(S)_VIEJA(S)> <KEY_PROYECTO_NUEVO> [KEY_PADRE_NUEVO]")
        print("Ejemplo (una): python3 jira_migrate_task.py \"E00033336-14\" \"INTDATALB\"")
        print('Ejemplo (varias, comas): python3 jira_migrate_task.py "INTOLD-1,INTOLD-2,INTOLD-3" "INTDATALB"')
        print("Ejemplo con Padre: python3 jira_migrate_task.py \"INTDATALB-352\" \"INTDATALB\" \"INTDATALB-12\"")
        sys.exit(1)

    old_issue_keys = parse_old_issue_keys_csv(sys.argv[1])
    if not old_issue_keys:
        print("Error: indica al menos una clave de tarea origen (ej. PROJ-123 o PROJ-1,PROJ-2).")
        sys.exit(1)

    new_project_key = sys.argv[2].upper().strip()
    new_parent_key = sys.argv[3].upper().strip() if len(sys.argv) > 3 else None

    print(f"=== Iniciando migración ({len(old_issue_keys)} tarea(s)) ===")
    print(f"Tarea(s) vieja(s) (origen): {', '.join(old_issue_keys)}")
    print(f"Proyecto nuevo (destino): {new_project_key}")
    if new_parent_key:
        print(f"Padre nuevo (especificado): {new_parent_key}")
    print(f"Dominio Jira: {DOMAIN}")
    print("-" * 50)

    auth = HTTPBasicAuth(EMAIL, API_TOKEN)

    failed = []
    for idx, old_issue_key in enumerate(old_issue_keys, start=1):
        if len(old_issue_keys) > 1:
            print(f"\n>>> Migración {idx}/{len(old_issue_keys)}: {old_issue_key}\n")

        try:
            migrate_one_issue(old_issue_key, new_project_key, new_parent_key, auth)
        except requests.exceptions.RequestException as e:
            print(f"\n[ERROR] {old_issue_key}: problema al comunicarse con la API de Jira: {e}")
            if e.response is not None:
                print(f"Detalles del error: {e.response.text}")
            failed.append(old_issue_key)
        except ValueError as e:
            print(f"\n[ERROR] {old_issue_key}: {e}")
            failed.append(old_issue_key)

    if len(old_issue_keys) > 1:
        print("\n" + "=" * 50)
        ok = len(old_issue_keys) - len(failed)
        print(f"Resumen: {ok} correcta(s), {len(failed)} fallida(s).")
        if failed:
            print(f"Fallidas: {', '.join(failed)}")
    if failed:
        sys.exit(1)

if __name__ == "__main__":
    main()
