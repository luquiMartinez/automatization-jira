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

---

## 3. Creador de Sub-tareas de Set Up (`jira_create_preset_tasks.py`)

### ¿Para qué sirve?
Este script crea automáticamente las 4 sub-tareas obligatorias para el inicio de un proyecto, vinculándolas a sus respectivas tareas "Padre" (Billable y Non-Billable) según la configuración.

**Tareas que genera:**
- **REUI** - {Nombre Proyecto} (Hija de Billable)
- **GG** - {Nombre Proyecto} (Hija de Billable)
- **REUE** - {Nombre Proyecto} (Hija de Billable)
- **AM** - {Nombre Proyecto} - NB (Hija de Non-Billable)

### ¿Cómo usarlo y ejecutarlo?
El script requiere tres parámetros:
1. La **URL** del proyecto o del tablero en Jira (solo con la clave en la ruta no basta para el nombre legible: el script consulta la API).
2. El **ID de la tarea Billable** (ej. `E00033336-14`).
3. El **ID de la tarea No Billable** (ej. `E00033336-1`).

**Nombre en los títulos de las sub-tareas:** se obtiene automáticamente de Jira. Si la URL incluye un tablero (`.../projects/CLAVE/boards/123...`), se usa el **nombre del tablero** Kanban. Si no, el **nombre del proyecto** (Administración del proyecto → Detalles). Si la API no responde, se usa la clave del proyecto como respaldo. Si el nombre en Jira empieza por `REUE - `, `REUI - `, etc., el script quita ese prefijo para no repetirlo en plantillas como `REUE - {nombre}`.

**Comando en la terminal:**
```bash
python3 jira_create_preset_tasks.py "URL_DEL_PROYECTO_O_TABLERO" "ID_BILLABLE" "ID_NO_BILLABLE"
```

**Ejemplo de ejecución (URL solo de proyecto — se usa el nombre del proyecto en Jira):**
```bash
python3 jira_create_preset_tasks.py "https://ddm-monks.atlassian.net/jira/software/c/projects/E00033336" "E00033336-14" "E00033336-1"
```

**Ejemplo si quieres el nombre del tablero Kanban (incluye `/boards/` en la URL):**
```bash
python3 jira_create_preset_tasks.py "https://ddm-monks.atlassian.net/jira/software/c/projects/E00033336/boards/4888" "E00033336-14" "E00033336-1"
```

---

## 4. Migrador y Clonador de Tareas (`jira_migrate_task.py`)

### ¿Para qué sirve?
Este script automatiza la clonación/migración de una tarea de un proyecto origen (viejo) a un proyecto destino (nuevo) de forma premium. 

**Características clave:**
- **Preserva el Nombre y la Descripción:** Copia el summary y, cuando la API lo permite, el formato enriquecido (ADF) de la descripción. Si hubo que quitar adjuntos o medios del ADF, se añade al **inicio** de la descripción un aviso y luego el texto migrable. Si no se puede migrar nada útil, la descripción en destino será un texto breve del estilo *«Descripción en la tarea original»* con **enlace clicable** a la issue origen.
- **Trazabilidad de Enlaces:** Crea un **enlace nativo en Jira** (tipo *Relates*) que conecta la tarea vieja con la nueva de forma interactiva.
- **Comentarios Cruzados:** Agrega de forma automática comentarios cruzados con enlaces interactivos en ambas tareas indicando que la tarea ha sido migrada (por ejemplo, en la tarea vieja deja un link directo a la nueva y viceversa).
- **Soporte para Padres/Epics:** Si el proyecto de destino requiere que las tareas pertenezcan a un Padre o Epic para ser creadas, puedes pasar opcionalmente el ID del padre como tercer parámetro del script.

### ¿Cómo usarlo y ejecutarlo?
El script requiere dos parámetros obligatorios y uno opcional:
1. El **ID de la(s) tarea(s) vieja(s)** (ej. `INTDATALB-352`). Puedes indicar **varias a la vez**, separadas por comas y sin espacios obligatorios: `INTOLD-1,INTOLD-2,INTOLD-3`. Se migran **en secuencia** (una detrás de otra en la misma ejecución); al final verás un resumen si hubo más de una.
2. El **ID del proyecto nuevo** (ej. `INTDATALB`).
3. *(Opcional)* El **ID del padre o Epic** en el nuevo proyecto (ej. `INTDATALB-12`). El mismo padre opcional se aplica a **todas** las tareas del lote cuando lo pasas.

**Comando básico (una tarea, sin padre):**
```bash
python3 jira_migrate_task.py "ID_TAREA_VIEJA" "ID_PROYECTO_NUEVO"
```

**Varias tareas en un solo comando:**
```bash
python3 jira_migrate_task.py "INTOLD-10,INTOLD-11,INTOLD-12" "INTDATALB"
```

**Comando con padre/Epic (obligatorio en proyectos con validaciones):**
```bash
python3 jira_migrate_task.py "ID_TAREA_VIEJA" "ID_PROYECTO_NUEVO" "ID_TAREA_PADRE"
```

**Ejemplo de ejecución con Epic/Padre (varias tareas, mismo padre destino):**
```bash
python3 jira_migrate_task.py "INTDATALB-352,INTDATALB-353" "INTDATALB" "INTDATALB-12"
```

**Alternativa en shell** (mismo proyecto y padre, una invocación por clave):  
`for k in INTOLD-1 INTOLD-2; do python3 jira_migrate_task.py "$k" "INTDATALB"; done`

