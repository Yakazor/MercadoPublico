# Informe ejecutivo: Herramientas Programa PET 2026

**🟡 RECOMENDACIÓN CONDICIONADA** · 🟡 GO CON CONDICIONES

## Resumen general

- **Licitación:** [1090-17-LE26](https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion=1090-17-LE26) (LE)
- **Organismo comprador:** CORP NACIONAL FORESTAL (Región del Maule)
- **Fecha de cierre:** 2026-11-03 09:00
- **Monto referencial:** $19.504.636
- **Ítems:** 13 (54% con precio de mercado)

## Análisis económico

| Concepto | Monto (neto) |
|---|---:|
| Costos directos (mercadería a precio de tienda) | $6.331.303 |
| IVA de las compras (sin crédito fiscal) | $1.202.948 |
| Logística (despacho 6 %, zona media) | $379.878 |
| Horas hombre (10.25 h × $6.000) | $61.500 |
| Garantía de fiel cumplimiento | $0 |
| Costo financiero (30 días hasta el pago) | $113.014 |
| Subcontratación | $0 |
| **Costo total** | **$8.088.643** |
| Ingreso (oferta sugerida) | $9.493.156 |
| **Margen bruto** | $1.958.905 (21 %) |
| **Margen neto** | $1.404.513 (15 %) |
| Rentabilidad sobre costos | 17 % |
| Punto de equilibrio (oferta mínima con IVA) | $9.625.485 |
| Oferta sugerida con IVA | $11.296.856 |

**Riesgos financieros:** 6 de 13 ítems sin precio de mercado: el costo real es mayor.; La mayoría de los precios no está verificada en la página de la tienda.; 1 de 7 precios son de productos aproximados (otra medida, marca o modelo)..

## Análisis operacional

- **Capacidad de cumplimiento:** factibilidad operativa media, complejidad media.
- **Recursos requeridos:** capital de trabajo de unos $7.534.251 con IVA para comprar la mercadería, 10.25 horas de trabajo y transporte a Región del Maule.
- **Dependencias críticas:** stock y precio del proveedor al momento de la orden de compra; precios de tienda sin verificar hasta abrir cada link.
- **Requisitos técnicos, garantías, experiencia y certificaciones:** están en las bases y anexos de la ficha (la API no los entrega). Revísalos antes de ofertar.

## Análisis de plazos

- **Días para el cierre:** 7
- **Viabilidad:** Alta.
- **Mitigación:** pedir cotización hoy (correos abajo), confirmar stock por escrito y tener un segundo proveedor.

## Riesgos detectados

- 6 de 13 ítems sin precio de mercado: el costo real es mayor.
- La mayoría de los precios no está verificada en la página de la tienda.
- 1 de 7 precios son de productos aproximados (otra medida, marca o modelo).

## Proveedores recomendados

| # | Proveedor | Especialidad | Correo | Sitio web | Contacto | Respuesta / entrega | Costo referencial |
|---:|---|---|---|---|---|---|---|
| 1 | Sodimac | Herramientas de jardín: palas, rastrillos, barrehojas, tijerones (opción usada en el presupuesto) | por confirmar | [web](https://www.sodimac.cl/) | — | por confirmar | Precio de tienda en el presupuesto |
| 2 | Falabella (vende Sodimac) | Azadones Tramontina (opción usada en el presupuesto) | por confirmar | [web](https://www.falabella.com/falabella-cl/) | — | por confirmar | Precio de tienda en el presupuesto |
| 3 | Ferretería La Reguera SpA | Herramientas manuales, insumos agrícolas y de jardinería (Villa Alegre, Maule); venta por mayor y stock por confirmar | por confirmar | — | — | por confirmar | — |

Prioridad: los que cubren más líneas primero. Riesgo: precios al detalle; pedir precio por volumen.

## Conclusión ejecutiva

**🟡 RECOMENDACIÓN CONDICIONADA.** La oportunidad es rentable, pero depende de cumplir las condiciones indicadas.

Condiciones:
- Conseguir precio de los ítems que faltan antes de ofertar.
- Confirmar que los productos aproximados cumplen la especificación de las bases (o cotizar el exacto).

## Supuestos

Despacho por zona {'cercana': 0.03, 'media': 0.06, 'lejana': 0.09, 'extrema': 0.12}; 4 h base + 0.25 h por línea + 3 h de entrega a $6.000/h; garantía 5 % sobre 1000 UTM (UTM $72.151) con costo de emisión 2 %; costo financiero 1.5 % mensual. Probabilidad de adjudicación: heurística. Se cambian en config.yaml > evaluacion.
