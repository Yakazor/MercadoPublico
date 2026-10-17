# Rutina «Actualizar Radar de Licitaciones»

Instrucciones para la sesión de Claude que mantiene al día el radar y su dashboard
(https://claude.ai/artifact/AUMtv926GXLeg1H82EDWrn, tipo Dashboard: sus datos son
documentos `datasets/<id>` con archivos adjuntos). Repositorio Yakazor/MercadoPublico,
rama `feature/api-mercadopublico`. Escribe todo (mensajes y commits) en español. El
ticket `MP_TICKET` nunca va en código, logs ni mensajes. Cada pedido es independiente:
sigue los pasos desde el principio aunque esta conversación tenga pedidos anteriores.
`<tmp>` es tu scratchpad (o una carpeta nueva en /tmp).

Hay tres pedidos posibles:

- **ACTUALIZACIÓN** (la rutina programada y el botón «Actualizar ahora»): datos de la
  API, órdenes de compra, presupuestos y dashboard. **No** busca precios de mercado
  nuevos: cuestan tiempo y plan, y el usuario elige qué licitaciones presupuestar.
- **PRECIOS para: <códigos>** (botón «Buscar precios» del dashboard o pedido en el chat):
  busca precios de mercado solo para esas licitaciones (máximo 5; si piden más, haz las
  5 primeras y dilo).
- **PRUEBA**: no cambies nada; prueba cada herramienta (git push --dry-run, Artifact
  list, ArtifactData list de `datasets`, WebSearch, Workflow disponible) y responde
  cuáles funcionan.

## ACTUALIZACIÓN

1. Repo al día: `git fetch origin feature/api-mercadopublico && git checkout feature/api-mercadopublico && git reset --hard origin/feature/api-mercadopublico`.
2. Anota el sha de la rama datos: `git ls-remote origin refs/heads/datos`.
3. Dispara los workflows (radar y OC) con un push al archivo disparador:
   `date -u +%Y-%m-%dT%H:%MZ > .github/disparar/actualizar.txt && git add .github/disparar/actualizar.txt && git commit -m "Actualizar radar (rutina)" && git push origin HEAD:feature/api-mercadopublico`.
   Si el push falla por red, reintenta hasta 4 veces (esperas de 2, 4, 8 y 16 s). Si falla
   por permisos, sigue con los últimos datos publicados y dilo en el resumen.
4. Espera a que la rama datos cambie: el radar publica primero (5–20 min) y las OC
   después (2–60 min). Revisa `git ls-remote origin refs/heads/datos` cada 3 minutos con
   un loop de Bash en segundo plano (nunca un sleep largo en primer plano), hasta ver dos
   cambios o 100 minutos en total.
5. Clona la rama datos: `git clone -q --depth 1 --branch datos https://github.com/Yakazor/MercadoPublico.git <tmp>/datos`.
6. Presupuestos: `python3 scripts/presupuesto.py --items <tmp>/datos/items.json --licitaciones <tmp>/datos/licitaciones.json --mercado-json <tmp>/mercado.json`.
7. `python3 -m pytest -q`. Si pasan y cambió algo en `informes/`, commit en español solo de
   `informes/` y push (mismos reintentos).
8. Dashboard: ver «Subir al dashboard» con licitaciones.json, precios.json, items.json y
   meta.json de `<tmp>/datos` y `<tmp>/mercado.json`.
9. Resumen de 3–6 líneas: licitaciones vigentes, rango de días de OC, presupuestos con
   precios y cualquier error.

## PRECIOS para: <códigos>

1. Pasos 1 y 5 de ACTUALIZACIÓN (sin disparar workflows).
2. `python3 scripts/seleccionar_mercado.py --items <tmp>/datos/items.json --licitaciones <tmp>/datos/licitaciones.json --salida <tmp>/lote.json --codigos <códigos separados por coma>`.
3. Corre el workflow guardado `precios-mercado-chile` (`.claude/workflows/precios-mercado-chile.js`)
   con args `{"hoy": "<AAAA-MM-DD>", "archivo": "<tmp>/lote.json", "lote": [{"codigo", "nombre"} de cada licitación de lote.json]}`.
   Si no puedes usar Workflow, busca tú con WebSearch siguiendo las reglas de ese archivo
   (tiendas chilenas, nunca inventar precios ni links, convertir a la unidad pedida, IVA).
4. Guarda el resultado (`{"licitaciones": [...]}`) en `<tmp>/resultado.json` y corre
   `python3 scripts/guardar_mercado.py <tmp>/resultado.json`.
5. Pasos 6 y 7 de ACTUALIZACIÓN (presupuestos, tests, commit de `informes/` y push).
6. Dashboard: «Subir al dashboard» con `<tmp>/mercado.json` (y items.json si cambió).
7. Resumen: por licitación, ítems con precio, costo, oferta total y si supera lo que el
   Estado pagó o el monto estimado.

## Subir al dashboard

1. Sube cada archivo como asset, uno por llamada: herramienta Artifact, `action: publish`,
   `url` del dashboard, `asset: true`, `file_path`.
2. Con ArtifactData (`url` del dashboard) lee `datasets` (list) y haz un `batch` con un
   `update` por archivo, con `if_version` = la versión leída:
   `{"source": {"kind": "file", "name": "<archivo>.json", "url": "/_blob/<id del asset>"}, "updated": {"at": "<ISO ahora>", "by": "Claude"}}`.
   Los ids de dataset son licitaciones, precios, items, mercado y meta. Si un batch falla
   por versión, vuelve a leer y reintenta una vez.
