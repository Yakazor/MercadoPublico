# Rutina «Actualizar Radar de Licitaciones»

Instrucciones para la sesión de Claude que mantiene al día el radar. Repositorio
Yakazor/MercadoPublico, rama `feature/api-mercadopublico`. La plataforma
(https://radar-mercadopublico.streamlit.app, `plataforma/app.py`) lee sola la rama `datos` y
`informes/`: no hay que subirle nada. Los datos de la API se actualizan solos en GitHub (radar
los días hábiles en la mañana; Compras Ágiles cada 3 horas, que se publican al terminar); esta
rutina agrega lo que necesita a Claude y gasta créditos: precios de mercado, proveedores y el
análisis. Escribe todo (mensajes y commits) en español. El
ticket `MP_TICKET` nunca va en código, logs ni mensajes. Cada pedido es independiente:
sigue los pasos desde el principio aunque esta conversación tenga pedidos anteriores.
`<tmp>` es tu scratchpad (o una carpeta nueva en /tmp).

Hay tres pedidos posibles:

- **ACTUALIZACIÓN** (la tarea programada «Actualizar Radar de Licitaciones», días hábiles 8:59
  hora de Chile, o «actualiza el radar» en el chat): revisa que los datos estén al día, busca
  precios de mercado para hasta 4 licitaciones nuevas (elegidas solas: compra y venta directa,
  ítems concretos, 3+ días para el cierre), presupuestos, evaluación comercial y publica.
- **PRECIOS para: <códigos>** (pedido en el chat; el dashboard copia el texto «busca precios de …»):
  busca precios de mercado solo para esas licitaciones (máximo 5; si piden más, haz las
  5 primeras y dilo).
- **PRUEBA**: no cambies nada; prueba cada herramienta (git push --dry-run, WebSearch,
  Workflow disponible, `gh workflow list`) y responde cuáles funcionan.

## ACTUALIZACIÓN

0. Dependencias (una vez por sesión): `pip install -q -r requirements.txt pytest`.
1. Repo al día: `git fetch origin feature/api-mercadopublico && git checkout feature/api-mercadopublico && git reset --hard origin/feature/api-mercadopublico`.
2. Clona la rama datos: `git clone -q --depth 1 --branch datos https://github.com/Yakazor/MercadoPublico.git <tmp>/datos`.
   Si `generado` de `<tmp>/datos/meta.json` tiene **menos de 6 horas**, usa esos datos y salta
   al paso 6. Si no, anota el sha (`git ls-remote origin refs/heads/datos`) y sigue.
3. Dispara los workflows (radar y OC) con un push al archivo disparador. Cada paso va en
   su propia llamada, sin `;`, `&&`, `cd` ni pipes (así calzan con los permisos de
   `.claude/settings.json`; un comando compuesto lo bloquea el modo automático):
   1. Con la herramienta Write, escribe en `.github/disparar/actualizar.txt` la fecha y
      hora UTC actual (`AAAA-MM-DDTHH:MMZ`).
   2. Bash: `git add .github/disparar/actualizar.txt`
   3. Bash: `git commit -m "Actualizar radar (rutina)"`
   4. Bash: `git push origin HEAD:feature/api-mercadopublico`
   Si el push falla por red, reintenta hasta 4 veces (esperas de 2, 4, 8 y 16 s); si lo
   rechaza porque la rama avanzó, `git pull --rebase origin feature/api-mercadopublico` y
   vuelve a hacer push. Si falla por permisos, sigue con los últimos datos publicados y
   dilo en el resumen.
4. Espera a que la rama datos cambie: el radar publica primero (5–20 min) y las OC
   después (2–60 min). Revisa `git ls-remote origin refs/heads/datos` cada 3 minutos con
   un loop de Bash en segundo plano (nunca un sleep largo en primer plano), hasta ver dos
   cambios o 100 minutos en total.
5. Vuelve a clonar la rama datos (paso 2, borrando antes `<tmp>/datos`).
5b. **Precios de mercado** (gasta créditos; máximo 4 licitaciones por corrida):
   1. `python3 scripts/seleccionar_mercado.py --items <tmp>/datos/items.json --licitaciones <tmp>/datos/licitaciones.json --salida <tmp>/lote.json --maximo 4 --compras-agiles 2`
      (elige abiertas sin precios, 3+ días para el cierre, ítems concretos, sin servicios ni registro ISP;
      2 cupos para Compras Ágiles, primero de la Región Metropolitana).
   2. Si el lote tiene licitaciones, pasos 3 y 4 de «PRECIOS para» (workflow `precios-mercado-chile`
      o WebSearch con sus reglas; `guardar_mercado.py`). Prioriza tiendas y distribuidores de Santiago.
6. Presupuestos: `python3 scripts/presupuesto.py --items <tmp>/datos/items.json --licitaciones <tmp>/datos/licitaciones.json --mercado-json <tmp>/mercado.json`.
6b. **Evaluación comercial** (ver «Evaluación comercial» al final): corre el script y
   completa proveedores y el Claude Log de las 3 mejores oportunidades.
7. `python3 -m pytest -q`. Si pasan y cambió algo en `informes/`: agrega una línea a la bitácora de
   `.claude/AVANCES.md` (fecha, licitaciones con precios nuevos, decisiones), `git add informes .claude/AVANCES.md`,
   `git commit -m "<mensaje en español>"` y `git push origin HEAD:feature/api-mercadopublico`,
   cada uno en su propia llamada (mismos reintentos). El push dispara «Verificar precios e
   informes PDF», que abre cada tienda y rehace los PDF.
8. Publica los precios nuevos en la plataforma sin esperar: `gh workflow run radar-diario.yml -R Yakazor/MercadoPublico --ref feature/api-mercadopublico -f solo_exportar=true`
   (no llama a la API). Si `gh` no puede, no pasa nada: «Compras Ágiles» los publica en menos de 3 horas.
9. Resumen de 3–6 líneas con PushNotification: licitaciones con precios nuevos y su decisión,
   las 3 mejores oportunidades (de `informes/evaluacion/README.md`), Compras Ágiles abiertas
   (`compras_agiles` en meta.json) y cualquier error. Termina con el link de la plataforma.

## PRECIOS para: <códigos>

1. Pasos 0, 1 y 5 de ACTUALIZACIÓN (sin disparar workflows).
2. `python3 scripts/seleccionar_mercado.py --items <tmp>/datos/items.json --licitaciones <tmp>/datos/licitaciones.json --salida <tmp>/lote.json --codigos <códigos separados por coma>`.
3. Corre el workflow guardado `precios-mercado-chile` (`.claude/workflows/precios-mercado-chile.js`)
   con args `{"hoy": "<AAAA-MM-DD>", "archivo": "<tmp>/lote.json", "lote": [{"codigo", "nombre"} de cada licitación de lote.json]}`.
   Si no puedes usar Workflow, busca tú con WebSearch siguiendo las reglas de ese archivo
   (tiendas chilenas, nunca inventar precios ni links, convertir a la unidad pedida, IVA).
4. Guarda el resultado (`{"licitaciones": [...]}`) en `<tmp>/resultado.json` y corre
   `python3 scripts/guardar_mercado.py <tmp>/resultado.json`.
5. Pasos 6, 6b, 7 y 8 de ACTUALIZACIÓN (presupuestos, evaluación, tests, commit y publicar).
6. Resumen: por licitación, ítems con precio, costo, oferta total y si supera lo que el
   Estado pagó o el monto estimado. Envíalo con PushNotification.

## Subir al dashboard (antiguo, solo si el usuario lo pide)

El dashboard artefacto (https://claude.ai/artifact/AUMtv926GXLeg1H82EDWrn) quedó reemplazado por la
plataforma. Para actualizarlo igual:

1. Sube cada archivo como asset, uno por llamada: herramienta Artifact, `action: publish`,
   `url` del dashboard, `asset: true`, `file_path`.
2. Con ArtifactData (`url` del dashboard) lee `datasets` (list) y haz un `batch` con un
   `update` por archivo, con `if_version` = la versión leída:
   `{"source": {"kind": "file", "name": "<archivo>.json", "url": "/_blob/<id del asset>"}, "updated": {"at": "<ISO ahora>", "by": "Claude"}}`.
   Los ids de dataset son licitaciones, precios, items, mercado y meta. Si un batch falla
   por versión, vuelve a leer y reintenta una vez.

## Evaluación comercial

Objetivo: después de cada actualización de datos, dejar en `informes/evaluacion/` el
Excel (`Licitaciones_evaluadas.xlsx`: hojas Licitaciones, Evaluación y Claude Log), el
resumen ejecutivo (`README.md`) y, para las mejores N, el informe ejecutivo, la hoja
GO / NO GO y los borradores de correo (`licitaciones/<codigo>_*.md`). Los supuestos de
costos están en `config.yaml > evaluacion`. GitHub vuelve a correr el script en el
workflow «Verificar precios e informes PDF» y genera los PDF.

1. `python3 scripts/evaluar_licitaciones.py --items <tmp>/datos/items.json --licitaciones <tmp>/datos/licitaciones.json`.
2. Lee `informes/evaluacion/README.md`. Para las 3 primeras que no sean NO GO:
   - Abre su informe y revisa riesgos y condiciones.
   - **Proveedores:** busca con WebSearch (máximo 3 búsquedas por licitación) distribuidores
     chilenos de lo que piden, priorizando los de la región de entrega o Santiago. Escribe
     `informes/evaluacion/proveedores/<codigo>.json`: lista de
     `{"nombre", "correo", "web", "contacto", "especialidad", "respuesta", "entrega", "costo_referencial", "fuente"}`.
     **Nunca inventes correos, teléfonos ni precios:** lo que no aparezca en un resultado
     de búsqueda va como `null` (el informe dirá «por confirmar»). `fuente` = la URL de
     donde salió el dato.
3. Escribe `<tmp>/log.json` con tu análisis en una sola entrada:
   `{"licitaciones_procesadas": "...", "resultado": "...", "riesgos": "...", "decisiones": "...", "recomendaciones": "..."}`
   (concreto: qué códigos, qué decidiste y por qué, qué debe hacer el usuario hoy).
4. Vuelve a correr el paso 1 agregando `--registrar <tmp>/log.json` (queda en la hoja
   Claude Log y en `claude_log.json`; la entrada automática del día se reemplaza, las tuyas se conservan).
5. **Borradores en Gmail** (solo si tienes las herramientas de Gmail y el proveedor tiene
   correo confirmado): un borrador por proveedor con el asunto y cuerpo de
   `licitaciones/<codigo>_correos.md`. Nunca envíes: el usuario revisa y envía.

