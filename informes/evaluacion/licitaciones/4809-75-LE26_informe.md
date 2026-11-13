# Informe ejecutivo: MATERIALES DE FERRETERIA

**⚪ SIN DECISIÓN: FALTAN PRECIOS** · ⚪ FALTA PRECIO

## Resumen general

- **Licitación:** [4809-75-LE26](https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion=4809-75-LE26) (LE)
- **Organismo comprador:** MINISTERIO DE OBRAS PUBLICAS DIREC CION GRAL DE OO PP DCYF (Región de la Araucanía)
- **Fecha de cierre:** 2026-11-17 16:00
- **Monto referencial:** $10.001.950
- **Ítems:** 9 (44% con precio de mercado)

## Análisis económico

| Concepto | Monto (neto) |
|---|---:|
| Costos directos (mercadería a precio de tienda) | $3.838.488 |
| IVA de las compras (sin crédito fiscal) | $729.313 |
| Logística (despacho 9 %, zona lejana) | $345.464 |
| Horas hombre (9.25 h × $6.000) | $55.500 |
| Garantía de fiel cumplimiento | $0 |
| Costo financiero (30 días hasta el pago) | $68.517 |
| Subcontratación | $0 |
| **Costo total** | **$5.037.282** |
| Ingreso (oferta sugerida) | $5.755.429 |
| **Margen bruto** | $1.187.628 (21 %) |
| **Margen neto** | $718.147 (12 %) |
| Rentabilidad sobre costos | 14 % |
| Punto de equilibrio (oferta mínima con IVA) | $5.994.365 |
| Oferta sugerida con IVA | $6.848.961 |

**Riesgos financieros:** 5 de 9 ítems sin precio de mercado: el costo real es mayor.; La mayoría de los precios no está verificada en la página de la tienda.; 4 de 4 precios son de productos aproximados (otra medida, marca o modelo)..

## Análisis operacional

- **Capacidad de cumplimiento:** factibilidad operativa baja, complejidad media.
- **Recursos requeridos:** capital de trabajo de unos $4.567.801 con IVA para comprar la mercadería, 9.25 horas de trabajo y transporte a Región de la Araucanía.
- **Dependencias críticas:** stock y precio del proveedor al momento de la orden de compra; precios de tienda sin verificar hasta abrir cada link.
- **Requisitos técnicos, garantías, experiencia y certificaciones:** están en las bases y anexos de la ficha (la API no los entrega). Revísalos antes de ofertar.

## Análisis de plazos

- **Días para el cierre:** 4
- **Viabilidad:** Media.
- **Mitigación:** pedir cotización hoy (correos abajo), confirmar stock por escrito y tener un segundo proveedor.

## Riesgos detectados

- 5 de 9 ítems sin precio de mercado: el costo real es mayor.
- La mayoría de los precios no está verificada en la página de la tienda.
- 4 de 4 precios son de productos aproximados (otra medida, marca o modelo).
- Cierra en 4 día(s): poco tiempo para cotizar con proveedores.
- Entrega en Región de la Araucanía: despacho caro y lento desde Santiago.

## Proveedores recomendados

| # | Proveedor | Especialidad | Correo | Sitio web | Contacto | Respuesta / entrega | Costo referencial |
|---:|---|---|---|---|---|---|---|
| 1 | Sodimac (Bauker) | Precio publicado para 2 línea(s) | por confirmar | [web](https://www.sodimac.cl/sodimac-cl/product/343609/electrodo-6011-1-8-1-kg) | — | por confirmar | — |
| 2 | Sodimac (Revor) | Precio publicado para 2 línea(s) | por confirmar | [web](https://www.sodimac.cl/sodimac-cl/lista/CATG11126/Esmaltes-Sinteticos/) | — | por confirmar | — |

Prioridad: los que cubren más líneas primero. Riesgo: precios al detalle; pedir precio por volumen.

## Conclusión ejecutiva

**⚪ SIN DECISIÓN: FALTAN PRECIOS.** Hay precio para 44% de las líneas (mínimo 80%): todavía no se puede decidir.

Condiciones:
- Conseguir precio de las 5 líneas que faltan: con 4 de 9 el margen sale de una parte del pedido.

## Supuestos

Despacho por zona {'cercana': 0.03, 'media': 0.06, 'lejana': 0.09, 'extrema': 0.12}; 4 h base + 0.25 h por línea + 3 h de entrega a $6.000/h; garantía 5 % sobre 1000 UTM (UTM $72.151) con costo de emisión 2 %; costo financiero 1.5 % mensual. Probabilidad de adjudicación: heurística. Se cambian en config.yaml > evaluacion.
