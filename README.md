# Radar de Licitaciones — Mercado Público

Detecta licitaciones activas en ChileCompra para dos rubros y estima precios
adjudicados a partir de órdenes de compra históricas:

1. **Insumos médicos no regulados y aseo** (guantes, mascarillas, desinfectantes…)
2. **Consultoría en gestión, BI y control de gestión** (Power BI, dashboards, indicadores…)

Los resultados se guardan en SQLite y se exportan a CSV/Excel listos para Power BI.

## Estructura

```
config.yaml                 # rubros, palabras clave, pausas y rutas
.env.example                # plantilla del ticket (MP_TICKET)
src/radar/
  cliente_api.py            # HTTP: pausas, reintentos con espera creciente, errores
  licitaciones.py           # activas del día + detalle por código
  ordenes_compra.py         # OC por fecha + resumen de precios
  filtro.py                 # detección de rubro por palabras clave
  modelos.py                # mapeo JSON → columnas (único archivo a ajustar si cambia la API)
  almacenamiento.py         # SQLite + exportación CSV/Excel
scripts/
  probar_api.py             # una llamada real: muestra la estructura del JSON
  radar_diario.py           # ejecución diaria del radar
  ordenes_historicas.py     # precios adjudicados por rubro
tests/                      # pruebas sin conexión a la API
data/                       # base y exportaciones (no se versiona)
```

## Instalación

Requiere Python 3.10 o superior.

```bash
git clone https://github.com/Yakazor/MercadoPublico.git
cd MercadoPublico
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Configurar el ticket

1. Solicita tu ticket en https://api.mercadopublico.cl (requiere Clave Única).
2. Copia la plantilla y pega el ticket:
   ```bash
   cp .env.example .env        # Windows: copy .env.example .env
   ```
   ```
   MP_TICKET=TU-TICKET-AQUI
   ```
3. `.env` está en `.gitignore`: **nunca** se sube al repositorio. El ticket
   tampoco aparece en logs ni mensajes de error.

## Ejecución

**1. Probar la conexión (una sola llamada):**
```bash
python scripts/probar_api.py                        # listado de activas
python scripts/probar_api.py --codigo 1234-56-LE26  # detalle de una licitación
python scripts/probar_api.py --fecha-oc 08102026    # OC de un día + detalle de la primera
```
También puedes correrlo sin instalar nada desde GitHub: pestaña **Actions →
Probar API Mercado Público → Run workflow** (usa el secret `MP_TICKET` del repo).
Muestra la estructura del JSON y guarda la respuesta en `data/muestra_api.json`.
Si algún campo no coincide con `src/radar/modelos.py`, ajústalo ahí.

**2. Radar diario:**
```bash
python scripts/radar_diario.py --limite 10   # prueba rápida
python scripts/radar_diario.py               # ejecución completa
```
Genera en `data/exportaciones/`:
- `licitaciones_AAAA-MM-DD.csv/.xlsx` — foto del día (histórico)
- `licitaciones_actual.csv/.xlsx` — siempre el mismo nombre: **conecta Power BI aquí**

Columnas: código, nombre, organismo, unidad de compra, región, comuna, monto
estimado, moneda, tipo, fecha de publicación, fecha de cierre, estado, rubro,
palabras detectadas, **días restantes**, link a la ficha, primera detección.

**3. Órdenes de compra históricas (precios adjudicados):**
```bash
python scripts/ordenes_historicas.py --dias 30
python scripts/ordenes_historicas.py --desde 2026-09-01 --hasta 2026-09-30
```
Genera `oc_items_*.csv/.xlsx` (una fila por ítem con precio unitario neto,
proveedor y organismo) y `oc_resumen_precios_*.csv/.xlsx` (mín, p25, mediana,
p75 y máx por producto). Los días ya procesados se saltan: puedes cortar y
reanudar. Usa `--reprocesar` para forzar la descarga.

> **Volumen real:** un solo día trae ~18.000 órdenes de compra (medido el
> 08-10-2026). El listado es una llamada, pero el detalle se pide solo para las
> OC cuyo nombre calza con tus rubros. Aun así, para rangos largos ejecútalo
> por tramos.
>
> **Ojo con la fecha:** la consulta por `fecha` devuelve OC con movimiento ese
> día, no solo las creadas ese día (ej. una OC de abril que se recepcionó en
> octubre). Para el análisis usa la columna `fecha_creacion`. Si una OC aparece
> en varios días se guarda una sola vez.
>
> En la API, el `Total` de cada ítem suele venir en 0; el script lo recalcula
> como cantidad × precio unitario neto.

## Ajustar los rubros

Edita `config.yaml`:
- `palabras_clave`: se comparan sin tildes ni mayúsculas y por palabra completa
  ("aseo" no coincide con "paseo"). **Usa frases** ("artículos de aseo",
  "consultoría en gestión"): en la primera corrida real, las palabras sueltas
  "aseo", "limpieza", "consultoría" y "asesoría" trajeron 123 resultados, de los
  cuales ~90 eran servicios de aseo, limpieza de fosas u obras civiles.
- `excluir`: descarta el rubro si la frase aparece en cualquier texto.
- `excluir_en_nombre`: descarta el rubro si la frase aparece **en el nombre**
  (ej. "servicios de aseo", "inspección fiscal"), sin afectar compras de
  productos cuya descripción mencione esas palabras.
- Para revisar el filtro: `python scripts/resumen_md.py --auditoria` lista
  todo lo detectado con las palabras que coincidieron.
- `filtro_preliminar_por_nombre: true` pide el detalle solo de las licitaciones
  cuyo nombre ya coincide (rápido). Con `false` revisa también descripción e
  ítems de todas (más completo, pero muchas más llamadas).

## Límites de la API

`config.yaml > api` controla la pausa entre llamadas (2 s por defecto) y los
reintentos (4, con esperas de 2, 4, 8 y 16 s) ante errores 5xx, 429,
"peticiones simultáneas" o cortes de red. Los errores definitivos (ticket
inválido, código inexistente) no se reintentan.

## Programar la ejecución diaria

- **Windows (Programador de tareas):** acción
  `C:\ruta\MercadoPublico\.venv\Scripts\python.exe scripts\radar_diario.py`
  con "Iniciar en" = carpeta del proyecto.
- **Linux/Mac (cron):** `0 8 * * 1-5 cd /ruta/MercadoPublico && .venv/bin/python scripts/radar_diario.py`

## Conectar Power BI

*Obtener datos → Texto/CSV* → `data/exportaciones/licitaciones_actual.csv`
(delimitador punto y coma, UTF-8) o *Excel* → `licitaciones_actual.xlsx`.
Para análisis históricos, conecta directo a `data/radar.db` vía ODBC de SQLite.

## Pruebas

```bash
python -m pytest
```
