# Avances y traspaso

Bitácora para que cualquier sesión o modelo retome el trabajo donde quedó. **Léela primero.**
Al cerrar cada avance: actualiza este archivo (estado, siguiente paso), haz commit y push.

## Cómo trabajar en este repo

- Idioma: español (código, comentarios, commits, PR y respuestas al usuario).
- Ramas: `feature/api-mercadopublico` es la principal (los workflows corren ahí). Cada tarea va
  en su rama y termina con un pull request hacia la principal. Hoy la rama de trabajo es
  `feature/plataforma`.
- Pruebas: `python3 -m pytest -q` (sin conexión a la API). La plataforma: `pip install -r
  plataforma/requirements.txt` y `streamlit run plataforma/app.py`.
- Repositorio público: **nunca** subir RUT, domicilios, claves ni órdenes llenas. Van en
  `.streamlit/secrets.toml` (ignorado) o en `proveedores/ordenes_proveedor/` (ignorado).
- Nunca inventar precios, correos, teléfonos ni links. Los correos a proveedores son
  borradores: nunca se envían solos.
- Un commit que solo toca `informes/` dispara «Verificar precios e informes PDF»; si es un
  commit intermedio, agrega `[skip actions]` al mensaje.
- Pie de commits y PR: el que indique la sesión (Co-Authored-By / link de la sesión).

## Estado (actualizado 2026-10-25)

| Tema | Estado |
|---|---|
| Radar, Compra Ágil, presupuestos, informes PDF | En producción (GitHub Actions en `feature/api-mercadopublico`) |
| Orden de compra al proveedor | Unido (PR #1) |
| Evaluación GO / NO GO, Excel con Claude Log, correos | PR #2 abierto (`feature/ordenes-compra`) |
| Plataforma web (Streamlit) | PR #3 abierto (`feature/plataforma`, parte de `feature/ordenes-compra`) |
| Workflow «Órdenes de compra históricas» | **Causa encontrada y corregida en `feature/plataforma`:** una OC trae un carácter de control («10U\x02POCA») y openpyxl rechazaba el Excel (`IllegalCharacterError`). `texto_excel`/`sin_formulas` lo quitan. Se arregla en producción al unir el PR #3. Los errores de los workflows ahora quedan como anotaciones (`gh api repos/Yakazor/MercadoPublico/check-runs/<job id>/annotations`) |

PRs: https://github.com/Yakazor/MercadoPublico/pull/2 y https://github.com/Yakazor/MercadoPublico/pull/3
(unir el 2 antes que el 3).

Manuales (Claude Docs): orden de compra https://claude.ai/artifact/VqeWE84qTfsjj2xj3NJk5W ·
guía de despacho y factura https://claude.ai/artifact/XSskNUJg2g5E1HFud8UQ5U

## Siguientes pasos sugeridos

- Unir PR #2 y luego PR #3 (la corrección de «Órdenes de compra históricas» y la publicación de
  Compras Ágiles cada 3 horas solo corren en producción después de unir).
- Publicar la plataforma en Streamlit Community Cloud (README, «Plataforma web») con `clave` y
  `github_token` en los secretos.
- Ideas pendientes: botón «Pedir análisis a Claude», borradores en Gmail desde la plataforma.

## Tarea en curso: plataforma (pedido del 25-10)

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
- [ ] Confirmar que «Órdenes de compra históricas» pasa con la corrección (corrida 40146638863 en
      `feature/plataforma`)

## Bitácora

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
