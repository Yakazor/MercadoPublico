# Rutina «Actualizar Radar de Licitaciones»

Instrucciones para la sesión de Claude que mantiene al día el radar y su dashboard
(https://claude.ai/artifact/AUMtv926GXLeg1H82EDWrn, tipo Dashboard: sus datos son
documentos `datasets/<id>` con archivos adjuntos). Repositorio Yakazor/MercadoPublico,
rama `feature/api-mercadopublico`. Escribe todo (mensajes y commits) en español. El
ticket `MP_TICKET` nunca va en código, logs ni mensajes. Cada pedido es independiente:
sigue los pasos desde el principio aunque esta conversación tenga pedidos anteriores.
`<tmp>` es tu scratchpad (o una carpeta nueva en /tmp).

Hay tres pedidos posibles:

- **ACTUALIZACIÓN** (la rutina programada o «actualiza el radar» en el chat): datos de la
  API, órdenes de compra, presupuestos y dashboard. **No** busca precios de mercado
  nuevos: cuestan tiempo y plan, y el usuario elige qué licitaciones presupuestar.
- **PRECIOS para: <códigos>** (pedido en el chat; el dashboard copia el texto «busca precios de …»):
  busca precios de mercado solo para esas licitaciones (máximo 5; si piden más, haz las
  5 primeras y dilo).
- **PRUEBA**: no cambies nada; prueba cada herramienta (git push --dry-run, Artifact
  list, ArtifactData list de `datasets`, WebSearch, Workflow disponible) y responde
  cuáles funcionan.

## ACTUALIZACIÓN

0. Dependencias (una vez por sesión): `pip install -q -r requirements.txt pytest`.
1. Repo al día: `git fetch origin feature/api-mercadopublico && git checkout feature/api-mercadopublico && git reset --hard origin/feature/api-mercadopublico`.
2. Anota el sha de la rama datos: `git ls-remote origin refs/heads/datos`.
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
5. Clona la rama datos: `git clone -q --depth 1 --branch datos https://github.com/Yakazor/MercadoPublico.git <tmp>/datos`.
6. Presupuestos: `python3 scripts/presupuesto.py --items <tmp>/datos/items.json --licitaciones <tmp>/datos/licitaciones.json --mercado-json <tmp>/mercado.json`.
6b. **Evaluación comercial** (ver «Evaluación comercial» al final): corre el script y
   completa proveedores y el Claude Log de las 3 mejores oportunidades.
7. `python3 -m pytest -q`. Si pasan y cambió algo en `informes/`: `git add informes`,
   `git commit -m "<mensaje en español>"` y `git push origin HEAD:feature/api-mercadopublico`,
   cada uno en su propia llamada (mismos reintentos).
8. Resumen de 3–6 líneas (decisiones GO / NO GO de `informes/evaluacion/README.md`, licitaciones vigentes, Compras Ágiles abiertas — `compras_agiles`
   en meta.json; si es null, el paso «Compras Ágiles» del workflow falló o no corrió —,
   rango de días de OC, presupuestos con precios y cualquier error). Envíalo con PushNotification **antes** del paso 9, terminado
   en «Para ver los datos en el dashboard, aprueba la subida en esta sesión».
9. Dashboard: ver «Subir al dashboard» con licitaciones.json, precios.json, items.json y
   meta.json de `<tmp>/datos` y `<tmp>/mercado.json`. Subir archivos a un artefacto pide la
   aprobación del usuario en la app: es el último paso para que todo lo demás ya esté hecho
   si nadie aprueba. Si una subida se rechaza, no reintentes: termina y dilo.

## PRECIOS para: <códigos>

1. Pasos 0, 1 y 5 de ACTUALIZACIÓN (sin disparar workflows).
2. `python3 scripts/seleccionar_mercado.py --items <tmp>/datos/items.json --licitaciones <tmp>/datos/licitaciones.json --salida <tmp>/lote.json --codigos <códigos separados por coma>`.
3. Corre el workflow guardado `precios-mercado-chile` (`.claude/workflows/precios-mercado-chile.js`)
   con args `{"hoy": "<AAAA-MM-DD>", "archivo": "<tmp>/lote.json", "lote": [{"codigo", "nombre"} de cada licitación de lote.json]}`.
   Si no puedes usar Workflow, busca tú con WebSearch siguiendo las reglas de ese archivo
   (tiendas chilenas, nunca inventar precios ni links, convertir a la unidad pedida, IVA).
4. Guarda el resultado (`{"licitaciones": [...]}`) en `<tmp>/resultado.json` y corre
   `python3 scripts/guardar_mercado.py <tmp>/resultado.json`.
5. Pasos 6 y 7 de ACTUALIZACIÓN (presupuestos, tests, commit de `informes/` y push).
6. Resumen: por licitación, ítems con precio, costo, oferta total y si supera lo que el
   Estado pagó o el monto estimado. Envíalo con PushNotification antes del paso 7.
7. Dashboard (último paso, pide aprobación del usuario): «Subir al dashboard» con
   `<tmp>/mercado.json` (y items.json si cambió).

## Subir al dashboard

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

