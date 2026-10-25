# Avances y traspaso

Bitácora para que cualquier sesión o modelo retome el trabajo donde quedó. **Léela primero.**
Al cerrar cada avance: actualiza este archivo (estado, siguiente paso), haz commit y push.

## Cómo trabajar en este repo

- Idioma: español (código, comentarios, commits, PR y respuestas al usuario).
- Ramas: `feature/api-mercadopublico` es la principal (los workflows corren ahí). Cada tarea va
  en su rama y termina con un pull request hacia la principal. `feature/ordenes-compra` y
  `feature/plataforma` ya están unidas: la próxima tarea parte de la principal al día.
- Pruebas: `python3 -m pytest -q` (sin conexión a la API). La plataforma: `pip install -r
  plataforma/requirements.txt` y `streamlit run plataforma/app.py`.
- Repositorio público: **nunca** subir RUT, domicilios, claves ni órdenes llenas. Van en
  `.streamlit/secrets.toml` (ignorado) o en `proveedores/ordenes_proveedor/` (ignorado).
- Nunca inventar precios, correos, teléfonos ni links. Los correos a proveedores son
  borradores: nunca se envían solos.
- Un commit que solo toca `informes/` dispara «Verificar precios e informes PDF»; si es un
  commit intermedio, agrega `[skip actions]` al mensaje.
  Ojo: al poner una rama al día con la principal, el push también lleva los informes que regeneró
  el bot y vuelve a dispararlo en esa rama (deja un commit de informes y después conflictos): el
  commit de arriba del push debe llevar `[skip actions]`.
- Pie de commits y PR: el que indique la sesión (Co-Authored-By / link de la sesión).
- Pull requests: `gh pr create` usa GraphQL y está bloqueado en estas sesiones; créalos con
  `gh api repos/Yakazor/MercadoPublico/pulls -f title=… -f head=<rama> -f base=feature/api-mercadopublico -F body=@<archivo>`.
  El modo automático no deja unir un PR sin revisión: lo une la usuaria en GitHub (o lo pide explícitamente).

## Estado (actualizado 2026-10-25, 14:00 UTC)

| Tema | Estado |
|---|---|
| Radar, Compra Ágil, presupuestos, informes PDF | En producción (GitHub Actions en `feature/api-mercadopublico`). Compras Ágiles cada 3 horas (y se publican al terminar), OC 9:11 UTC todos los días. Radar: 11:07 UTC de lunes a viernes; con el PR #9 pasa a **todos los días 10:07 UTC** (7:07 en Chile en verano, 6:07 en invierno) |
| Orden de compra al proveedor | Unido (PR #1) |
| Evaluación GO / NO GO, Excel con Claude Log, correos | Unido (PR #2, 25-10) |
| Plataforma web (Streamlit) | Publicada en https://radar-mercadopublico.streamlit.app desde la cuenta de Streamlit de Yakazor (archivo principal `plataforma/app.py`, rama `feature/api-mercadopublico`; secretos `clave` y `github_token`). PR #3 a #6 unidos: menú arriba, tablas de ancho fijo (caben en 1366 px), «Recordarme» 30 días, filtros GO / NO GO y «Compra y venta directa», 💲 en el nombre = ya tiene precios de tiendas. Si la página muestra la versión anterior: Manage app → ⋮ → Reboot app (con la cuenta Yakazor) |
| Rutina con créditos de Claude | Tarea programada «Actualizar Radar de Licitaciones» (`trig_016CgWNwJxAa22bBQMtx7z4U`), **todos los días 7:59** America/Santiago (pedido del 25-10: «a las 8:00 de lunes a lunes»; antes días hábiles 8:59). Corre en la sesión dedicada `session_01XXFwMR2USPWee8pWawbiB7`, creada con el repo. Su prompt solo se puede cambiar desde esa sesión (el horario sí desde cualquiera). «Ejecutar ahora» (`fire_trigger`) **no** usa esa sesión: crea una nueva sin repo y falla (así falló la primera corrida, 25-10 03:55 UTC, con dos avisos al celular). En una sesión nueva `add_repo` existe, pero el modo automático lo niega. Para correrla a mano: escribirle «ACTUALIZACIÓN» a la sesión dedicada. Prueba de corrida programada hacia la sesión dedicada (`trig_01Bf1ZoTveVMJLP3jPi5bD71`, 04:56 UTC): **funcionó**: llegó a la sesión dedicada, que respondió «Prueba recibida. Sí, esta sesión tiene el repositorio». Las corridas programadas sí usan esa sesión. **Primera corrida programada: 25-10 11:00–11:20 UTC, bien** (precios para 4 licitaciones, commit e88ad5c de informes, publicación; ~US$ 3,6 de créditos). |
| Workflow «Órdenes de compra históricas» | Corregido (PR #3): una OC traía un carácter de control («10U\x02POCA») y openpyxl rechazaba el Excel; `texto_excel`/`sin_formulas` lo quitan. Verificado: corrida 40150220712. Los errores de los workflows quedan como anotaciones (`gh api repos/Yakazor/MercadoPublico/check-runs/<job id>/annotations`) |

PRs unidos: #1 a #8. Pendiente de unir: https://github.com/Yakazor/MercadoPublico/pull/9 (radar diario y corrección de la rutina).

Manuales (Claude Docs): orden de compra https://claude.ai/artifact/VqeWE84qTfsjj2xj3NJk5W ·
guía de despacho y factura https://claude.ai/artifact/XSskNUJg2g5E1HFud8UQ5U

## Siguientes pasos sugeridos

- Unir el PR #9. Sin él, el radar de GitHub sigue de lunes a viernes. La rutina también lee el `.claude/RUTINA.md`
  viejo, que con datos frescos se salta los precios; el prompt de la tarea igual pide los precios.
- La rutina busca precios con WebSearch y no puede abrir las tiendas: quedan «sin verificar» hasta que
  «Verificar precios e informes PDF» (GitHub) los revisa después del push (así pasó el 25-10: efd4b54).
- Ideas pendientes: botón «Pedir análisis a Claude», borradores en Gmail desde la plataforma, y que
  «Verificar precios e informes PDF» no reescriba los ~160 PDF cuando solo cambia su fecha interna
  (cada corrida deja un commit con PDF de igual tamaño, p. ej. 20e7f53).

## Última tarea: actualización diaria con créditos de Claude (pedido del 25-10)

- [x] Tarea programada todos los días 7:59 hora de Chile (aplicado en la tarea)
- [x] Radar de GitHub todos los días 10:07 UTC (PR #9)
- [x] `.claude/RUTINA.md` paso 2: con datos frescos salta a los precios (5b), no al 6 (PR #9)
- [x] Diagnóstico de la corrida fallida («Ejecutar ahora» crea una sesión sin repo; `add_repo` negado)
- [x] Prueba de una corrida programada hacia la sesión dedicada (`trig_01Bf1ZoTveVMJLP3jPi5bD71`, 04:56 UTC): ver «Estado»
- [ ] Unir el PR #9 (usuaria)
- [x] Primera corrida programada (25-10 10:59 UTC): terminó bien a las 11:20 UTC

## Tarea anterior: plataforma (pedido del 25-10) — terminada

- [x] Plataforma: Inicio, Licitaciones, Compras Ágiles, Evaluación, Orden de compra (PR #3)
- [x] Bitácora de avances (este archivo) y `CLAUDE.md` que apunta aquí
- [x] Lanzar ahora la actualización de la API (corridas 40145670239 radar y 40145668711
      Compras Ágiles, 25-10 00:10 UTC)
- [x] Página «Actualizar datos»: botón que lanza los workflows (`src/radar/actualizacion.py`,
      secreto `github_token` + `clave`), últimas corridas cada 30 s y recarga al terminar el radar
- [x] «Compras Ágiles» publica al terminar: lanza el radar en modo «solo exportar» (antes solo
      se publicaban con el radar de días hábiles; los datos tenían Compras Ágiles del 23-10)
- [x] Página «Manuales»: PDF en `manuales/` (exportados de los Claude Docs), Guía del Radar,
      erratas, plantillas e informes de `informes/pdf/`
- [x] Auditar y corregir (falla de «Órdenes de compra históricas», JSON de la orden, margen de recarga)
- [x] Actualizar la descripción del PR #3
- [x] Confirmar que «Órdenes de compra históricas» pasa con la corrección: corrida 40146638863 en
      `feature/plataforma` terminó bien (antes fallaba en «Descargar órdenes de compra»)
- [x] Radar «solo exportar» con `run-name` propio («Publicar datos»): no bloquea «Actualizar ahora»

## Bitácora

- 2026-10-25 (rutina 11:00 UTC): datos `datos` del 25-10 08:16 (465 licitaciones, 1.596 Compras Ágiles).
  Precios con WebSearch (sin Workflow; la sesión no abre las tiendas: quedan sin verificar) para
  2452-25-LE26 tóner (14/18 ítems; GO con condiciones, pero la oferta supera el estimado),
  979-73-LE26 EPP (14/18; GO con condiciones, margen 16 %), 3384-167-COT26 libros (0/6) y
  1075956-166-COT26 oficina (0/5, especificación en anexo). Mejores: 3654-36-LE26, 612-44-LE26 y
  4768-55-LE26 (cierran 26-10; ya tenían proveedores). 482 pruebas OK.

- 2026-10-25: actualización diaria (pedido: «todos los días a las 8:00, de lunes a lunes»). Tarea de Claude
  todos los días 7:59 (aplicado); radar de GitHub todos los días 10:07 UTC y corrección de `.claude/RUTINA.md`
  paso 2 en el PR #9. Con datos frescos, y lo están siempre porque Compras Ágiles publica cada 3 horas, la rutina
  saltaba al paso 6 y nunca buscaba precios; ahora salta al 5b. La primera corrida falló porque «Ejecutar ahora»
  creó una sesión nueva sin repo (ver «Estado»).

- 2026-10-25: tarea programada creada y lanzada una vez. Una tarea con sesión nueva en cada corrida no
  sirve: esas sesiones no tienen el repo conectado y el modo automático les niega `add_repo` (probado en
  `session_01VZ5VVWs2D4QfuQfqbg4sYe`), por eso corre en una sesión dedicada creada con el repo
  (`create_session` con `source_url`).

- 2026-10-25: rutina con créditos de Claude: `.claude/RUTINA.md` ya no sube al dashboard (la plataforma
  lee sola), busca precios para hasta 4 licitaciones al día (`seleccionar_mercado.py --maximo 4
  --compras-agiles 2`, sin las que no son compra y venta directa) y publica con radar «solo exportar».
  Tarea programada «Actualizar Radar de Licitaciones», días hábiles 8:59 (America/Santiago).

- 2026-10-25: menú arriba y ⚙️ Supuestos en un botón (sin barra lateral: ~1.200 px útiles en 1366).
  Filtros y columnas «Decisión» (GO / con condiciones / NO GO / sin evaluar) y «Compra-venta»
  (`radar.plataforma.compra_venta`: ✅ productos para revender, ❌ servicios/ISP/licencias, ❓ bases);
  `item_concreto` se movió de `scripts/seleccionar_mercado.py` a `radar.plataforma`. 493 pruebas OK.

- 2026-10-25: «Recordarme en este equipo»: cookie `radar_acceso` (30 días) con una llave derivada de
  la clave (`comun.token_acceso`); se escribe con un componente invisible porque Streamlit solo lee
  cookies (`st.context.cookies`). «Cerrar sesión» en la barra lateral la borra. Probado en Chromium
  (recargar y abrir otra sección no piden la clave). 492 pruebas OK.

- 2026-10-25: las tablas no cabían en la pantalla de la usuaria (notebook 1366 px, ~904 px útiles
  con el menú abierto). Anchos fijos por columna, decisiones abreviadas («🟡 Con condiciones»),
  regiones cortas, 💲 = con precios de tiendas, ⚡ = Compra Ágil; organismo, tipo y link pasan a la
  ficha. Pruebas nuevas para el ranking y la ficha. 490 pruebas OK.

- 2026-10-25: creada de nuevo con `plataforma/app.py`: **la plataforma funciona** en
  https://radar-mercadopublico.streamlit.app (probada por la usuaria en incógnito). En su Chrome normal
  fallaban tablas e indicadores («Failed to fetch dynamically imported module»): copia defectuosa
  guardada o extensión; se arregla borrando los datos de ese sitio. Bajar los datos toma ~1,3 s y
  procesarlos ~0,2 s; la espera larga es el arranque de Streamlit Cloud cuando la app duerme.

- 2026-10-25: la plataforma se publicó en https://radar-mercadopublico.streamlit.app desde la cuenta
  Yakazor (Carlag96 no es admin del repo). El primer intento quedó con archivo principal
  `plataforma/evaluar.py` y la página salía en blanco: debe ser `plataforma/app.py`. Streamlit no deja
  cambiarlo: hay que borrar la app (guardando antes los secretos) y crearla de nuevo con el mismo URL.

- 2026-10-25: verificado en producción tras unir: «Órdenes de compra históricas» OK (40150220712,
  ya publica datos); «Compras Ágiles» (40150222091) lanzó sola «Publicar datos (solo exportar)»
  (40150264913, OK): `datos` del 24-10 22:25 con Compras Ágiles de las 22:20; informes regenerados
  (9e2fd96, 20e7f53). La plataforma lee bien esas corridas (`radar.actualizacion.corridas`).

- 2026-10-25: el usuario pidió unir: PR #2 y PR #3 unidos a `feature/api-mercadopublico`.

- 2026-10-25: PR #2 y #3 tenían conflictos con la principal solo en informes generados (las dos
  ramas corrieron «Verificar precios e informes PDF»). Resueltos tomando la versión de la principal
  (más reciente); ambos PR quedan «clean». La plataforma aún no está publicada: falta unir los PR
  y crear la app en share.streamlit.io (rama principal, `plataforma/app.py`, secretos).

- 2026-10-25: verificada la corrección de «Órdenes de compra históricas» (corrida 40146638863, éxito).
  Tarea del 25-10 terminada; PR #3 actualizado. Pendiente: que el usuario una los PR #2 y #3.

- 2026-10-25: causa de la falla diaria de «Órdenes de compra históricas»: carácter de control en
  una descripción de OC rompía la exportación a Excel. Corregido (y en la orden de compra y el
  Excel de evaluación). Carga de orden en JSON más robusta. 489 pruebas OK.

- 2026-10-25: radar lanzado a mano terminó bien: `datos` del 24-10 21:19 (465 licitaciones,
  1.600 Compras Ágiles). Auditoría de la plataforma: margen de recarga 5 min, ayuda del número
  de OC; prueba completa en Chromium OK con los datos nuevos.
- 2026-10-25: páginas «Actualizar datos» y «Manuales»; Compras Ágiles se publican al terminar;
  487 pruebas OK. Falta: auditoría y la falla de «Órdenes de compra históricas».
- 2026-10-25: plataforma web publicada en la rama `feature/plataforma` (PR #3), 482 pruebas OK.
  Pedido nuevo: bitácora, botón de actualización, manuales en PDF, auditoría.
