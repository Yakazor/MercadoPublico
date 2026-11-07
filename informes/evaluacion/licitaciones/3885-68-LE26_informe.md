# Informe ejecutivo: ADQ. EQUIPOS COMPUTACIONALES Y ACCESORIOS

**⚪ SIN DECISIÓN: FALTAN PRECIOS** · ⚪ FALTA PRECIO

## Resumen general

- **Licitación:** [3885-68-LE26](https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion=3885-68-LE26) (LE)
- **Organismo comprador:** I MUNICIPALIDAD DE PICA (Región de Tarapacá)
- **Fecha de cierre:** 2026-11-12 10:00
- **Monto referencial:** $10.000.000
- **Ítems:** 8 (50% con precio de mercado)

## Análisis económico

| Concepto | Monto (neto) |
|---|---:|
| Costos directos (mercadería a precio de tienda) | $5.383.983 |
| IVA de las compras (sin crédito fiscal) | $1.022.957 |
| Logística (despacho 12 %, zona extrema) | $646.078 |
| Horas hombre (9 h × $6.000) | $54.000 |
| Garantía de fiel cumplimiento | $0 |
| Costo financiero (30 días hasta el pago) | $96.104 |
| Subcontratación | $0 |
| **Costo total** | **$7.203.122** |
| Ingreso (oferta sugerida) | $8.072.744 |
| **Margen bruto** | $1.665.804 (21 %) |
| **Margen neto** | $869.622 (11 %) |
| Rentabilidad sobre costos | 12 % |
| Punto de equilibrio (oferta mínima con IVA) | $8.571.715 |
| Oferta sugerida con IVA | $9.606.566 |

**Riesgos financieros:** 4 de 8 ítems sin precio de mercado: el costo real es mayor.; La mayoría de los precios no está verificada en la página de la tienda.; 1 de 4 precios son de productos aproximados (otra medida, marca o modelo)..

## Análisis operacional

- **Capacidad de cumplimiento:** factibilidad operativa media, complejidad alta.
- **Recursos requeridos:** capital de trabajo de unos $6.406.940 con IVA para comprar la mercadería, 9 horas de trabajo y transporte a Región de Tarapacá.
- **Dependencias críticas:** stock y precio del proveedor al momento de la orden de compra; precios de tienda sin verificar hasta abrir cada link.
- **Requisitos técnicos, garantías, experiencia y certificaciones:** están en las bases y anexos de la ficha (la API no los entrega). Revísalos antes de ofertar.

## Análisis de plazos

- **Días para el cierre:** 5
- **Viabilidad:** Alta.
- **Mitigación:** pedir cotización hoy (correos abajo), confirmar stock por escrito y tener un segundo proveedor.

## Riesgos detectados

- 4 de 8 ítems sin precio de mercado: el costo real es mayor.
- Líneas con unidad Global/Kit: la cantidad real está en las bases.
- La mayoría de los precios no está verificada en la página de la tienda.
- 1 de 4 precios son de productos aproximados (otra medida, marca o modelo).
- Cierra en 5 día(s): poco tiempo para cotizar con proveedores.
- Entrega en Región de Tarapacá: despacho caro y lento desde Santiago.

## Proveedores recomendados

| # | Proveedor | Especialidad | Correo | Sitio web | Contacto | Respuesta / entrega | Costo referencial |
|---:|---|---|---|---|---|---|---|
| 1 | HyperPC (vende en Paris.cl) | PC gamer armados (Ryzen 7, 32 GB, 1 TB); referencia de las líneas 2 y 3 | por confirmar | [web](https://www.paris.cl/pc-gamer-amd-ryzen-7-8700-32gb-ddr5-1tb-rtx-5060-ti-16gb-MKZ8YH2GBG.html) | — | por confirmar | 2097990 |
| 2 | Tech Box SpA (vende en Paris.cl) | Periféricos Kensington (combo Pro Fit) | por confirmar | [web](https://www.paris.cl/combo-teclado-mouse-inalambrico-kensington-pro-fit-MKUVNRTPDG.html) | — | por confirmar | 36990 |

Prioridad: los que cubren más líneas primero. Riesgo: precios al detalle; pedir precio por volumen.

## Conclusión ejecutiva

**⚪ SIN DECISIÓN: FALTAN PRECIOS.** Hay precio para 50% de las líneas (mínimo 80%): todavía no se puede decidir.

Condiciones:
- Conseguir precio de las 4 líneas que faltan: con 4 de 8 el margen sale de una parte del pedido.

## Supuestos

Despacho por zona {'cercana': 0.03, 'media': 0.06, 'lejana': 0.09, 'extrema': 0.12}; 4 h base + 0.25 h por línea + 3 h de entrega a $6.000/h; garantía 5 % sobre 1000 UTM (UTM $72.151) con costo de emisión 2 %; costo financiero 1.5 % mensual. Probabilidad de adjudicación: heurística. Se cambian en config.yaml > evaluacion.
