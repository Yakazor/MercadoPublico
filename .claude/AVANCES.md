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
| Workflow «Órdenes de compra históricas» | Falla desde el 22-10 en «Descargar órdenes de compra» (por revisar) |

PRs: https://github.com/Yakazor/MercadoPublico/pull/2 y https://github.com/Yakazor/MercadoPublico/pull/3
(unir el 2 antes que el 3).

Manuales (Claude Docs): orden de compra https://claude.ai/artifact/VqeWE84qTfsjj2xj3NJk5W ·
guía de despacho y factura https://claude.ai/artifact/XSskNUJg2g5E1HFud8UQ5U

## Tarea en curso: plataforma (pedido del 25-10)

- [x] Plataforma: Inicio, Licitaciones, Compras Ágiles, Evaluación, Orden de compra (PR #3)
- [x] Bitácora de avances (este archivo) y `CLAUDE.md` que apunta aquí
- [ ] Lanzar ahora la actualización de la API (workflows «Radar diario» y «Compras Ágiles»)
- [ ] Botón en la plataforma para actualizar la API (dispara los workflows con un token de
      GitHub guardado en los secretos) y estado de las últimas corridas
- [ ] Sección «Manuales» en la plataforma con los PDF (manuales + guía + informes)
- [ ] Auditar y corregir todo lo anterior (incluye la falla de «Órdenes de compra históricas»)
- [ ] Actualizar la descripción del PR #3

## Bitácora

- 2026-10-25: plataforma web publicada en la rama `feature/plataforma` (PR #3), 482 pruebas OK.
  Pedido nuevo: bitácora, botón de actualización, manuales en PDF, auditoría.
