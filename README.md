# Radar de Licitaciones — Mercado Público

Detecta licitaciones activas en ChileCompra de productos que se pueden comprar y
revender sin grandes permisos, más un rubro de servicios, y estima precios
adjudicados a partir de órdenes de compra históricas:

1. **Insumos médicos no regulados y aseo** (guantes, mascarillas, desinfectantes…)
2. **Mobiliario** de oficina, escolar y almacenaje (sillas, escritorios, lockers…)
3. **Artículos de oficina y librería** (resmas, tóner, archivadores…)
4. **Computación y electrónica** (notebooks, monitores, impresoras, proyectores…)
5. **Ferretería y herramientas** (herramientas, pinturas, candados…)
6. **Electrodomésticos, hogar y menaje** (refrigeradores, vajilla, ropa de cama…)
7. **Vestuario, uniformes y textiles** (uniformes, calzado, ropa de trabajo…)
8. **Deporte, juguetes y material didáctico**
9. **Materiales de construcción, eléctricos e iluminación** (cemento, yeso, cables,
   luminarias, baterías…; sin obras ni instalación)
10. **Instrumental e insumos de laboratorio** (material de vidrio, microscopios,
    balanzas, pHmetros…; sin reactivos ni equipos en comodato)
11. **Repuestos, neumáticos, lubricantes y accesorios vehiculares** (sin vehículos
    ni combustibles)
12. **Seguridad, EPP, señalética y protección contra incendios** (cascos, conos,
    extintores, botiquines…; sin guardias ni armamento)
13. **Consultoría en gestión, BI y control de gestión** (servicio propio: Power BI,
    dashboards, indicadores, cursos de Excel/Power BI…)

Quedan fuera los productos que exigen permisos importantes (medicamentos,
alimentos, químicos peligrosos, combustibles, armas, vehículos), las obras y los
servicios. Los productos con registro ISP se marcan, no se excluyen.

Los resultados se guardan en SQLite y se exportan a CSV/Excel listos para Power BI.

Además detecta **Compras Ágiles** abiertas (compras de hasta 100 UTM, sin bases ni
garantías) con los mismos rubros: ver [Compra Ágil](#compra-ágil).

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
  presupuesto.py            # costo, oferta e IVA por licitación vs referencia OC
  censo.py                  # muestra de activas agrupada por segmento ONU
  orden_proveedor.py        # orden de compra a tu proveedor (planilla Excel)
scripts/
  probar_api.py             # una llamada real: muestra la estructura del JSON
  radar_diario.py           # ejecución diaria del radar
  ordenes_historicas.py     # precios adjudicados por rubro
  publicar_datos.py         # JSON del dashboard (rama datos)
  seleccionar_mercado.py    # elige las licitaciones a cotizar en el mercado
  guardar_mercado.py        # guarda los precios de mercado encontrados
  presupuesto.py            # informes de presupuesto (informes/presupuestos)
  censo_rubros.py           # censo de grupos de licitaciones
  informe_grupos.py         # informe de grupos (informes/grupos_licitaciones)
  orden_proveedor.py        # llena la orden de compra al proveedor desde un JSON
dashboard/index.html        # copia de la página del dashboard
informes/                   # presupuestos, precios de mercado y grupos (se versiona)
.claude/RUTINA.md           # instrucciones de la rutina de actualización
proveedores/                # orden de compra al proveedor:
  ORDEN_PROVEEDOR.md        #   instrucciones para llenarla (link desde .claude/)
  plantillas/               #   plantillas en blanco (persona natural y empresa)
  ordenes_proveedor/        #   órdenes llenas (no se versionan: traen RUT); solo ejemplo.json
.claude/workflows/          # búsqueda de precios de mercado en Chile
.github/workflows/          # radar, OC, censo y prueba de la API
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
defecto, últimos 7 días). Además corre solo todos los días y revisa los últimos 21
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
- `excluir_grupos`: suma listas compartidas de `grupos_exclusion` a
  `excluir_en_nombre`. El grupo `clinico` (implantes, catéteres, esterilización,
  insumos médicos…) lo usan los rubros de reventa: así "Clavo intramedular" no es
  ferretería ni "Balones de angioplastia" es deporte.
- Si una licitación calza en varios rubros, el principal es el que tiene claves en
  el nombre ("Uniformes y otros" con tablets en los ítems es vestuario); entre
  iguales, el que suma más claves. La columna `rubros_todos` los lista todos.
- **Criterio de reventa** (insumos y aseo): el radar busca productos que puedas
  comprar y revender tal cual. `especialidades` (angiografía, diálisis,
  traumatología…) marca licitaciones que suelen pedir dispositivos técnicos o de
  marca: ahí "insumos médicos" en el nombre no basta y deciden los ítems (una
  línea de guantes o gasas sí cuenta). Los productos con registro ISP no se
  excluyen: quedan marcados (ver Alertas regulatorias).
- `no_rescatan`: claves genéricas ("guantes", "cloro") que no anulan una
  exclusión de `excluir_en_nombre_salvo_clave_especifica` (EPP, agua): "EPP:
  guantes y lentes" se descarta, "EPP: guantes de nitrilo y mascarillas" no. Las exclusiones también se revisan en cada ítem: si todos los
  ítems están excluidos ("Guante cabritilla soldador"), un nombre genérico como
  "Guantes" se descarta.
- `ignorar`: nombres de unidades compradoras ("Dirección de Obras Municipales")
  que no deben contar ni excluir. Fuera del nombre, "Depto./Unidad de <clave>" se
  ignora solo; "área/oficina/sección de <clave>" solo si la clave es débil, y
  nunca tras "fortalecer", "implementar", "crear"… ("fortalecer la unidad de
  gestión estratégica" es lo que se contrata).
- Para revisar el filtro: `python scripts/resumen_md.py --auditoria` lista todo lo
  detectado con las palabras que coincidieron.
- `filtro_preliminar_por_nombre: true` pide el detalle solo de las licitaciones
  cuyo nombre trae una palabra clave o candidata (rápido). Con `false` revisa
  todas (más completo, pero muchas más llamadas).

En las **órdenes de compra** cada ítem se clasifica por su producto (y la
categoría ONU si el producto no lo dice; las exclusiones también se revisan en la
especificación del comprador y del proveedor). Si el producto calza con un rubro y
la categoría con otro, manda el producto: "Uniformes escolares" es vestuario aunque
su categoría ONU sea "Ropa, maletas y productos de aseo personal". En insumos, si la OC tiene un solo
ítem genérico, se usa el nombre de la OC cuando dice qué producto es ("Compra de
guantes de nitrilo"); no con nombres amplios (`palabras_amplias`: "insumos
médicos", "artículos de aseo"), que pueden traer un monitor o un despacho. En consultoría, la especificación del comprador solo
cuenta si el producto es un servicio compatible (`especificacion_si_producto`:
consultoría, asesoría, software, capacitación…) y los productos ONU genéricos
(`productos_genericos`: "Servicios de consultoría de gestión") no cuentan solos.
Solo se guardan los ítems de tus rubros, así el catering, los pasajes o un
monitor de una OC de "insumos clínicos" no entran al cálculo de precios.

La base guarda además el detalle compacto de cada OC revisada (tabla
`ordenes_compra_detalle`) y, por 90 días, el listado de códigos y nombres de cada
día. Si cambias `config.yaml`:
- la siguiente ejecución (radar u OC) reclasifica lo guardado sin llamar a la
  API: agrega los ítems que ahora calzan y quita los que ya no;
- la siguiente ejecución de OC descarga solo las OC de los últimos 90 días cuyo
  nombre ahora calza (p. ej. tras agregar "escobas") y que nunca se pidieron.

Para días más antiguos, o descargados antes de esta mejora, vuelve a
procesarlos con `--reprocesar`.

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

## Escala: detalles guardados y muestra de OC

- **Licitaciones:** el detalle de cada licitación candidata se guarda y se
  reutiliza; solo se vuelve a pedir si es nueva, si cambió su fecha de cierre en
  el listado o si pasaron `refrescar_detalle_licitacion_dias` (7). Así el radar
  diario pide unos cientos de detalles, no miles.
- **Órdenes de compra:** para los precios basta una muestra. Cada día se piden a
  lo más `ordenes_compra.maximo_por_rubro_y_dia` OC por rubro (60; insumos 200,
  consultoría 100, con `oc_maximo_por_dia`). La muestra es estable (por el código
  de la OC): reprocesar un día elige las mismas.

## Límites de la API

`config.yaml > api` controla la pausa entre llamadas (2 s por defecto) y los
reintentos (4, con esperas de 2, 4, 8 y 16 s) ante errores 5xx, 429,
"peticiones simultáneas" o cortes de red. Los errores definitivos (ticket
inválido, código inexistente) no se reintentan.

## Compra Ágil

`scripts/compra_agil.py` usa la API Compra Ágil v2 de ChileCompra
(`https://api2.mercadopublico.cl/v2/compra-agil`, el ticket va en el encabezado
`ticket`). La API es lenta (~10 compras cada ~5 s; con páginas más grandes responde
HTTP 504) y hay miles de Compras Ágiles abiertas, así que trabaja por tandas:

1. El workflow **«Compras Ágiles»** (`.github/workflows/compra-agil.yml`) corre cada
   3 horas y lista solo lo publicado desde la corrida anterior (un día a la vez, del
   más antiguo al más nuevo), en las regiones de `config.yaml > compra_agil > regiones`
   (vacío = todo Chile).
2. Las que pasan el filtro por nombre quedan **pendientes**; se pide su detalle
   (productos, cantidades, monto disponible, plazo y dirección de entrega, llamado),
   primero las que cierran antes, y se aplica el filtro completo y las alertas ISP.
3. La **memoria** (`data/compra_agil_estado.json`: hasta dónde se listó, abiertas,
   descartadas y pendientes) se guarda en la caché de Actions; las que cierran salen
   solas. Si la memoria se pierde, parte con los últimos `dias_iniciales` días.
4. El **radar diario** restaura `data/compras_agiles.json` (si tiene menos de 30 horas)
   y `publicar_datos.py` las suma a `licitaciones.json` e `items.json` con
   `tipo = "Compra Ágil"`: el dashboard, el simulador y «busca precios de <código>»
   funcionan igual que con una licitación.

- **Ticket:** usa el secreto `MP_TICKET_COMPRA_AGIL` si existe y, si no, `MP_TICKET`.
  Si la API responde 401/403, pide un ticket en https://www.chilecompra.cl/api/
  («Pide tu ticket», con ClaveÚnica) y guárdalo como `MP_TICKET_COMPRA_AGIL`.
- **HTTP 429:** es un límite de ritmo; se espera lo que indique la API (una vez) y, si
  vuelve, lo que falta queda pendiente para la próxima corrida.
- **Fechas:** en hora de Chile; `fecha_cierre` llega como `"2026-10-23 15:00"`.
- **Primer llamado** (`llamado = 1`): solo empresas de menor tamaño (una persona
  natural con inicio de actividades que vende poco califica como microempresa).
- **Cotización:** en Compra Ágil se ingresa el **total con IVA y despacho** y se
  deben cotizar todos los ítems.
- **Ficha:** `https://buscador.mercadopublico.cl/ficha?code=<código>`.

## Programar la ejecución diaria

- **Windows (Programador de tareas):** acción
  `C:\ruta\MercadoPublico\.venv\Scripts\python.exe scripts\radar_diario.py`
  con "Iniciar en" = carpeta del proyecto.
- **Linux/Mac (cron):** `0 8 * * 1-5 cd /ruta/MercadoPublico && .venv/bin/python scripts/radar_diario.py`

## Conectar Power BI

*Obtener datos → Texto/CSV* → `data/exportaciones/licitaciones_actual.csv`
(delimitador punto y coma, UTF-8, coma decimal: configuración regional es-CL) o *Excel* → `licitaciones_actual.xlsx`.
Para análisis históricos, conecta directo a `data/radar.db` vía ODBC de SQLite.

## Automatización en GitHub

Todo corre en GitHub Actions con el secret `MP_TICKET` (Settings → Secrets and
variables → Actions → New repository secret; nunca en el código ni en `.env`
subido):

| Workflow | Cuándo | Qué hace |
|---|---|---|
| `radar-diario.yml` | días hábiles en la mañana, manual o push a `.github/disparar/actualizar.txt` | radar + publica los JSON del dashboard en la rama `datos` |
| `ordenes-historicas.yml` | todos los días, manual o el mismo push | OC de los últimos 21 días + precios + presupuestos |
| `censo-rubros.yml` | manual | censo de grupos (rama `censo`) |
| `probar-api.yml` | manual | una llamada de prueba |
| `informes.yml` | cuando cambian los precios o presupuestos de `informes/` | abre cada tienda para verificar el precio, rehace los presupuestos y los PDF de `informes/pdf/` |

Los cuatro comparten el grupo de concurrencia `radar-db`: nunca llaman a
la API en paralelo con el mismo ticket. La base SQLite se guarda entre corridas
como caché/artefacto.

## Dashboard, rutina y presupuestos

El dashboard (artefacto de Claude) lee los JSON de la rama `datos` que sube la
**rutina «Actualizar Radar de Licitaciones»** (días hábiles 8:50, hora de Chile;
instrucciones en `.claude/RUTINA.md`).

- **Un solo artefacto:** el dashboard. claude.ai no deja que una página le mande
  mensajes a una sesión de Claude (lo rechaza con `blocked_by_policy`), así que los
  pedidos se hacen en el chat: «actualiza el radar» o «busca precios de <códigos>».
  Los botones del dashboard copian ese texto. Subir archivos al dashboard pide tu
  aprobación en la app de Claude: la rutina deja todo lo demás hecho, te avisa y
  la subida es el último paso.
- **Simular:** cualquier licitación muestra su presupuesto al tiro. Si ya tiene
  precios de tiendas (buscados por Claude con el workflow
  `.claude/workflows/precios-mercado-chile.js`, con links) se usan esos; si no,
  cada ítem se estima con lo que el Estado pagó en órdenes de compra: oferta =
  mediana pagada y costo = lo máximo que puedes pagar para tu margen. Solo quedan
  sin valor los ítems sin tiendas ni OC parecidas.
- **Presupuesto:** costo = opción más barata exacta o equivalente × 1,05 (otros
  costos); oferta = costo × (1 + margen, 20% por defecto) + IVA 19%. Se compara
  con lo que el Estado pagó por el mismo producto (mediana de OC) y con el monto
  estimado; si los supera, el informe lo advierte. En el dashboard puedes
  cambiar el margen.
- **Guía completa** (cómo funciona, cómo usarlo y cómo postular a Mercado Público):
  `informes/Guia_Radar_Licitaciones.pdf`.
- **Informes** (`informes/`): `presupuestos/<código>.md|csv`, precios de
  mercado en `mercado/<código>.json` y `grupos_licitaciones.md|csv` (todos los
  segmentos ONU con licitaciones activas vs los rubros del radar, para decidir
  si agregar grupos).

Los precios de mercado vienen de resultados de búsqueda (el entorno de Claude no
puede abrir sitios .cl). El workflow `informes.yml` abre cada link desde GitHub y
marca «Verificado: sí» solo si la página muestra ese precio (±3 %); si no, el
presupuesto dice qué encontró (otro precio, HTTP 403 o precio cargado con
JavaScript). Igual revisa stock y despacho antes de cotizar.

## Orden de compra al proveedor

Cuando aceptas una OC del Estado, le envías tu propia orden de compra a quien te vende la
mercadería. La planilla trae los datos del comprador (persona natural con giro, o
empresa), del proveedor, la referencia a la licitación y a la OC del Estado, el detalle
con subtotales, IVA y total como fórmulas, y las condiciones de entrega y pago.

```bash
python scripts/orden_proveedor.py --siguiente                    # próximo número OC-AAAA-NNN
python scripts/orden_proveedor.py --datos proveedores/ordenes_proveedor/OC-2026-001.json --pdf
python scripts/orden_proveedor.py --plantilla persona_natural     # plantilla en blanco
```

El formato de los datos está en `proveedores/ordenes_proveedor/ejemplo.json` (precio neto o con
IVA por ítem). Las órdenes llenas quedan en `proveedores/ordenes_proveedor/`, que no se sube al
repositorio porque trae RUT y datos personales. El PDF y el recálculo de totales usan
LibreOffice si está instalado. Manual de órdenes de compra en Mercado Público:
https://claude.ai/artifact/VqeWE84qTfsjj2xj3NJk5W
Manual de guía de despacho y factura electrónica (referencia 801 a la OC, Resolución
SII 154 desde el 1-11-2026): https://claude.ai/artifact/XSskNUJg2g5E1HFud8UQ5U

## Pruebas

```bash
python -m pytest
```
