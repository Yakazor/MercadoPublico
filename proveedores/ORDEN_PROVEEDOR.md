# Pedido «ORDEN DE COMPRA»: llenar la orden al proveedor

Instrucciones para la sesión de Claude cuando el usuario pide una orden de compra a su
proveedor (la que él le envía a la tienda o mayorista, no la OC del Estado). Escribe
todo en español. Trabaja en la rama `feature/ordenes-compra` y abre un pull request a
`feature/api-mercadopublico` al terminar cada tarea.

Todo lo de proveedores vive en `proveedores/`: estas instrucciones, `plantillas/` (plantillas
en blanco) y `ordenes_proveedor/` (órdenes llenas; solo `ejemplo.json` se versiona). El código
está en `src/radar/orden_proveedor.py` y `scripts/orden_proveedor.py`.

Manual completo (conceptos, ciclo, aceptación de la OC del Estado, factura y pago):
https://claude.ai/artifact/VqeWE84qTfsjj2xj3NJk5W

## Datos que pide la orden

Formato: `proveedores/ordenes_proveedor/ejemplo.json`. Por defecto el comprador es
**persona natural con giro** (`comprador.tipo = "persona_natural"`); `"empresa"` solo si
el usuario lo pide.

| Bloque | Campos | Obligatorio |
|---|---|---|
| Orden | `numero` (si falta: `--siguiente`), `fecha` (AAAA-MM-DD; si falta: hoy) | sí |
| Comprador | `nombre`, `rut`, `giro`, `domicilio`, `contacto` | sí |
| Proveedor | `razon_social`, `rut`, `vendedor`, `contacto` | razón social y RUT |
| Referencia | `licitacion`, `oc_estado` (ID de la OC que envió el organismo) | recomendado |
| Ítems | `codigo`, `descripcion`, `unidad`, `cantidad`, y `precio_unitario_neto` **o** `precio_con_iva` | descripción, cantidad y precio |
| Otros | `descuento` (pesos), `condiciones`: `lugar_entrega`, `fecha_entrega`, `flete`, `forma_pago`, `validez`, `observaciones` | no |

Si el usuario da una licitación con presupuesto en `informes/presupuestos/<codigo>.md`,
propón los ítems desde ahí (descripción, cantidad, mejor precio neto y tienda como
proveedor) y pide que los confirme.

## Pasos

1. Dependencias (una vez por sesión): `pip install -q -r requirements.txt`.
2. Reúne los datos del mensaje. Lo que falte y sea obligatorio, pregúntalo en un solo
   mensaje; no inventes RUT, nombres ni precios.
3. Escribe `proveedores/ordenes_proveedor/<numero>.json` (la carpeta está en `.gitignore`: trae RUT
   y datos personales y el repositorio es público; **nunca** hagas commit de esos archivos).
4. Genera: `python scripts/orden_proveedor.py --datos proveedores/ordenes_proveedor/<numero>.json --pdf`.
   El script avisa los datos que faltan y recalcula con LibreOffice si está instalado.
5. Revisa el resultado (totales, que nada se corte en el PDF) y entrega el `.xlsx` y el
   `.pdf` al usuario. Resume: número, proveedor, cantidad de ítems, neto, IVA y total.
6. Recuerda al usuario pedirle al proveedor confirmación escrita de stock, precio y plazo
   antes de aceptar la OC del Estado.

Precios con IVA se convierten a neto dividiendo por 1,19 y redondeando al peso.
