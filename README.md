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
p75 y máx por producto; las OC canceladas no se consideran). Los días ya
procesados se saltan: puedes cortar y reanudar. Usa `--reprocesar` para forzar
la descarga. `python scripts/resumen_oc.py --texto` muestra el resumen en pantalla.

Desde GitHub: **Actions → Órdenes de compra históricas → Run workflow** (por
defecto, últimos 7 días). Además corre solo cada sábado y revisa los últimos 21
días: los ya procesados se saltan y se reintentan los que quedaron pendientes.
Un día cuyas OC fallan por errores de la API no se marca como procesado (se
reintenta hasta 3 veces). Las fechas se calculan con la hora de Chile.

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

Edita `config.yaml` (los comentarios del archivo explican cada opción). Cómo se
comparan las frases: sin tildes, mayúsculas ni puntuación; cada palabra acepta
singular y plural ("guante" = "guantes"); entre palabras se aceptan conectores
("productos de aseo" = "productos aseo" = "productos para el aseo"); y siempre por
palabra completa ("aseo" no coincide con "paseo").

- `palabras_clave`: **usa frases** ("artículos de aseo", "consultoría en gestión").
  En la primera corrida real, las palabras sueltas "aseo", "limpieza",
  "consultoría" y "asesoría" trajeron 123 resultados, ~90 de ellos falsos
  (servicios de aseo, limpieza de fosas, obras civiles). Cuentan si aparecen en el
  **nombre o en los ítems**; en la descripción general, solo si el rubro tiene
  `detectar_en_descripcion: true` (en consultoría está apagado, porque la
  descripción suele nombrar unidades como "Depto. de Control de Gestión").
- `palabras_debiles`: claves que también son nombres de unidades o frases de
  informes ("control de gestión", "indicadores de gestión"): cuentan en el nombre;
  en los ítems, solo junto a otra clave.
- `palabras_candidatas`: frases amplias ("insumos clínicos", "consultoría") que,
  en el nombre, hacen que se revise el detalle; por sí solas no cuentan. En
  consultoría, si el nombre trae una candidata, la descripción cuenta cuando
  tiene 2 o más claves distintas.
- `usar_clasificacion_onu`: si la categoría/producto del clasificador ONU de
  Mercado Público cuenta como señal. Útil en insumos ("Guantes médicos"); apagado
  en consultoría, porque "Servicios de consultoría de gestión" se asigna a casi
  cualquier servicio profesional (médicos, abogados…).
- `excluir_en_nombre`: descarta siempre (ej. "servicio de aseo", "inspección fiscal").
- `excluir_en_nombre_salvo_clave`: descarta salvo que el nombre traiga otra palabra
  clave: "Compra de sondas" se descarta, "Gasas, guantes y sondas" no.
- `ignorar`: nombres de unidades compradoras ("Dirección de Obras Municipales")
  que no deben contar ni excluir.
- Para revisar el filtro: `python scripts/resumen_md.py --auditoria` lista todo lo
  detectado con las palabras que coincidieron.
- `filtro_preliminar_por_nombre: true` pide el detalle solo de las licitaciones
  cuyo nombre trae una palabra clave o candidata (rápido). Con `false` revisa
  todas (más completo, pero muchas más llamadas).

En las **órdenes de compra** cada ítem se clasifica por su producto (y la
categoría ONU si el producto no lo dice; las exclusiones también se revisan en la
especificación del comprador). Si la OC tiene un solo ítem genérico, se usa el
nombre de la OC. Solo se guardan los ítems de tus rubros,
así el catering, los pasajes o un monitor de una OC de "insumos clínicos" no
entran al cálculo de precios. Si cambias `config.yaml`, la siguiente ejecución
reclasifica lo ya guardado sin llamar a la API.

## Alertas regulatorias (ISP)

Una investigación del 12-10-2026 (normativa del ISP, Minsal y BCN) concluyó que
varios productos de la lista **no son "no regulados"**: guantes de látex y
quirúrgicos, jeringas y agujas, respiradores N95/KN95, alcohol gel,
desinfectantes y cloro, y jabón de manos. Sí se consideran no regulados:
guantes de nitrilo de examen (conviene confirmarlo por escrito con el ISP),
mascarillas quirúrgicas de 3 pliegues, pecheras, cofias, gasas, apósitos simples,
detergentes sin declaración desinfectante, papel higiénico y toallas.

No se excluye nada automáticamente: las licitaciones e ítems de OC llevan las
columnas `alertas_regulatorias` (qué registro exige) y `solo_regulados` (todo lo
que se compra es regulado), para filtrarlas en Power BI. En los resúmenes se
marcan con ⚠ (incluye regulados) y ⚠⚠ (solo regulados). Edita la sección
`alertas_regulatorias` de `config.yaml` para ajustarlas. Antes de ofertar,
confirma con el ISP y pide al proveedor el N° de registro de cada producto.

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
