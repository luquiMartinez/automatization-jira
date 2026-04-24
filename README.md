# Jira Automatization Scripts

Este repositorio contiene scripts en Python diseñados para automatizar tareas repetitivas en la gestión de tableros y flujos de trabajo en Jira Cloud.

## Requisitos Previos

Para ejecutar estos scripts, necesitas tener Python 3 instalado en tu computadora. Además, los scripts utilizan la librería `requests` para comunicarse con la API de Jira.

Puedes instalar la dependencia necesaria abriendo tu terminal y ejecutando:
```bash
python3 -m pip install requests
```

Antes de ejecutar los scripts, debes configurar tus credenciales de Jira. 
Crea (o edita si ya existe) un archivo llamado `config.json` en la misma carpeta donde están los scripts, con el siguiente formato:

```json
{
    "EMAIL": "tu_email@empresa.com",
    "API_TOKEN": "TU_TOKEN_DE_API_DE_JIRA"
}
```

Ambos scripts leerán automáticamente este archivo para autenticarse, por lo que es **muy seguro y fácil de compartir** (simplemente asegúrate de no subir tu `config.json` si vas a compartir el código en un repositorio público como GitHub, añadiéndolo al `.gitignore`).

---

## 1. Estandarizador de Tableros Kanban (`jira_workflow_automator.py`)

### ¿Para qué sirve?
Este script se encarga de forzar que cualquier tablero de Jira adopte una estructura estricta y estandarizada de 10 columnas en el siguiente orden:
`NOT STARTED`, `ESTIMATE`, `TO DO`, `IN PROGRESS`, `IN REVIEW`, `IN UAT`, `DEPLOY`, `DONE`, `CANCELLED`, `BLOCKED`.

Al ejecutarse, el script recolectará automáticamente todos los *status* existentes en el proyecto de Jira y los asignará a su columna correspondiente basándose en el nombre (también reconoce sinónimos básicos como "Completed" -> "DONE"). Además, configura correctamente el **Kanban Backlog** para mantener la vista del tablero limpia.

### ¿Cómo usarlo y ejecutarlo?
El script requiere un único parámetro: la URL directa a la configuración de columnas de tu tablero.

**Comando en la terminal:**
```bash
python3 jira_workflow_automator.py "URL_DEL_TABLERO"
```

**Ejemplo de ejecución:**
```bash
python3 jira_workflow_automator.py "https://ddm-monks.atlassian.net/jira/software/c/projects/INTLATSETL/boards/60/settings/columns"
```

---

## 2. Ocultador Dinámico de Tareas (`jira_hide_tasks.py`)

### ¿Para qué sirve?
Este script modifica el **Filtro Principal (JQL)** que alimenta a un tablero para excluir de la vista tareas específicas generadas en serie (ej. `E00033340-2`, `E00033340-3`). 

El script es "inteligente": no borra tu filtro original ni rompe sentencias como el `ORDER BY Rank ASC`. Lo que hace es leer la consulta actual e inyectarle una regla unificada (`AND issuekey NOT IN (...)`), respetando cualquier otra exclusión que ya tuvieras configurada previamente.

> **Importante:** Para que este script funcione, tu usuario en Jira debe ser el "Dueño" (Owner) del filtro del tablero, o tener otorgados permisos explícitos de "Edición" (Edit) sobre el mismo.

### ¿Cómo usarlo y ejecutarlo?
El script requiere tres parámetros obligatorios:
1. La **URL** del tablero.
2. El **Prefijo** o clave base de la tarea (ej. `E00033340`).
3. Los **Números** de las tareas a ocultar, separados por comas y sin espacios.

**Comando en la terminal:**
```bash
python3 jira_hide_tasks.py "URL_DEL_TABLERO" "PREFIJO" "NUMEROS"
```

**Ejemplo de ejecución:**
```bash
python3 jira_hide_tasks.py "https://ddm-monks.atlassian.net/jira/software/c/projects/E00033340/boards/4888" "E00033340" "2,3,4,5,6"
```
*(En el ejemplo anterior, el script se conectará a Jira y ocultará automáticamente las tareas E00033340-2, E00033340-3, E00033340-4, E00033340-5 y E00033340-6 del tablero 4888).*
