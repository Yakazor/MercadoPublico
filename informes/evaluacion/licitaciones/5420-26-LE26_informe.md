# Informe ejecutivo: Adquisición de equipos periféricos

**⚪ SIN DECISIÓN: FALTAN PRECIOS** · ⚪ FALTA PRECIO

## Resumen general

- **Licitación:** [5420-26-LE26](https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion=5420-26-LE26) (LE)
- **Organismo comprador:** GOBIERNO REGIONAL DE ARICA-PARINACOTA (Región de Arica y Parinacota)
- **Fecha de cierre:** 2026-11-16 15:30
- **Monto referencial:** $49.300.000
- **Ítems:** 7 (29% con precio de mercado)

## Análisis económico

| Concepto | Monto (neto) |
|---|---:|
| Costos directos (mercadería a precio de tienda) | $6.699.664 |
| IVA de las compras (sin crédito fiscal) | $1.272.936 |
| Logística (despacho 12 %, zona extrema) | $803.960 |
| Horas hombre (8.75 h × $6.000) | $52.500 |
| Garantía de fiel cumplimiento | $0 |
| Costo financiero (30 días hasta el pago) | $119.589 |
| Subcontratación | $0 |
| **Costo total** | **$8.948.649** |
| Ingreso (oferta sugerida) | $10.045.476 |
| **Margen bruto** | $2.072.876 (21 %) |
| **Margen neto** | $1.096.827 (11 %) |
| Rentabilidad sobre costos | 12 % |
| Punto de equilibrio (oferta mínima con IVA) | $10.648.892 |
| Oferta sugerida con IVA | $11.954.117 |

**Riesgos financieros:** 5 de 7 ítems sin precio de mercado: el costo real es mayor..

## Análisis operacional

- **Capacidad de cumplimiento:** factibilidad operativa baja, complejidad media.
- **Recursos requeridos:** capital de trabajo de unos $7.972.600 con IVA para comprar la mercadería, 8.75 horas de trabajo y transporte a Región de Arica y Parinacota.
- **Dependencias críticas:** stock y precio del proveedor al momento de la orden de compra; precios de tienda sin verificar hasta abrir cada link.
- **Requisitos técnicos, garantías, experiencia y certificaciones:** están en las bases y anexos de la ficha (la API no los entrega). Revísalos antes de ofertar.

## Análisis de plazos

- **Días para el cierre:** 2
- **Viabilidad:** Media.
- **Mitigación:** pedir cotización hoy (correos abajo), confirmar stock por escrito y tener un segundo proveedor.

## Riesgos detectados

- 5 de 7 ítems sin precio de mercado: el costo real es mayor.
- Cierra en 2 día(s): poco tiempo para cotizar con proveedores.
- Entrega en Región de Arica y Parinacota: despacho caro y lento desde Santiago.

## Proveedores recomendados

| # | Proveedor | Especialidad | Correo | Sitio web | Contacto | Respuesta / entrega | Costo referencial |
|---:|---|---|---|---|---|---|---|
| 1 | Intcomex Chile (mayorista) | Mayorista TI: monitores (ASUS) y periféricos; vende a revendedores | por confirmar | [web](https://www.intcomex.com) | Rosario Norte 615 piso 6, Las Condes; centro de distribución en Pudahuel (por confirmar) | por confirmar | — |
| 2 | Ingram Micro Chile (mayorista) | Mayorista TI; distribuidor de monitores BenQ en Chile | por confirmar | — | Av. Providencia 1760 piso 11 (por confirmar) | por confirmar | — |
| 3 | Lider / Paris (Logitech H390) | Referencia retail de auriculares H390 | por confirmar | [web](https://www.paris.cl/audifono-con-cable-logitech-h390-MK3AR3UUR1.html) | — | por confirmar | 33466 |

Prioridad: los que cubren más líneas primero. Riesgo: precios al detalle; pedir precio por volumen.

## Conclusión ejecutiva

**⚪ SIN DECISIÓN: FALTAN PRECIOS.** Hay precio para 29% de las líneas (mínimo 80%): todavía no se puede decidir.

Condiciones:
- Conseguir precio de las 5 líneas que faltan: con 2 de 7 el margen sale de una parte del pedido.

## Supuestos

Despacho por zona {'cercana': 0.03, 'media': 0.06, 'lejana': 0.09, 'extrema': 0.12}; 4 h base + 0.25 h por línea + 3 h de entrega a $6.000/h; garantía 5 % sobre 1000 UTM (UTM $72.151) con costo de emisión 2 %; costo financiero 1.5 % mensual. Probabilidad de adjudicación: heurística. Se cambian en config.yaml > evaluacion.
