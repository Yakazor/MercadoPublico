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

## Estado (actualizado 2026-10-25)

| Tema | Estado |
|---|---|
| Radar, Compra Ágil, presupuestos, informes PDF | En producción (GitHub Actions en `feature/api-mercadopublico`) |
| Orden de compra al proveedor | Unido (PR #1) |
| Evaluación GO / NO GO, Excel con Claude Log, correos | Unido (PR #2, 25-10) |
| Plataforma web (Streamlit) | Unida (PR #3, 25-10). Falta publicarla en share.streamlit.io (lo hace el usuario: README, «Plataforma web») |
| Workflow «Órdenes de compra históricas» | **Causa encontrada y corregida en `feature/plataforma`:** una OC trae un carácter de control («10U\x02POCA») y openpyxl rechazaba el Excel (`IllegalCharacterError`). `texto_excel`/`sin_formulas` lo quitan. En producción desde la unión del PR #3 (25-10); verificado: corrida 40150220712 terminó bien, incluido «Publicar datos para el dashboard». Los errores de los workflows ahora quedan como anotaciones (`gh api repos/Yakazor/MercadoPublico/check-runs/<job id>/annotations`) |

PRs unidos: https://github.com/Yakazor/MercadoPublico/pull/2 y https://github.com/Yakazor/MercadoPublico/pull/3

Manuales (Claude Docs): orden de compra https://claude.ai/artifact/VqeWE84qTfsjj2xj3NJk5W ·
guía de despacho y factura https://claude.ai/artifact/XSskNUJg2g5E1HFud8UQ5U

## Siguientes pasos sugeridos

- Publicar la plataforma en Streamlit Community Cloud (README, «Plataforma web») con `clave` y
  `github_token` en los secretos.
  Ojo: Streamlit exige ser **admin** del repositorio para publicar. `Yakazor/MercadoPublico` es de una
  cuenta personal (Yakazor); la usuaria (Carlag96) solo tiene permiso de escritura. Opciones: que
  Yakazor la publique, o publicarla desde un fork en Carlag96 (los datos se leen igual de la rama
  `datos` de Yakazor; manuales e informes se actualizan con «Sync fork»).
- Ideas pendientes: botón «Pedir análisis a Claude», borradores en Gmail desde la plataforma, y que
  «Verificar precios e informes PDF» no reescriba los ~160 PDF cuando solo cambia su fecha interna
  (cada corrida deja un commit con PDF de igual tamaño, p. ej. 20e7f53).

## Última tarea: plataforma (pedido del 25-10) — terminada

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
