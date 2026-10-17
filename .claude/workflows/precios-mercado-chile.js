export const meta = {
  name: 'precios-mercado-chile',
  description: 'Busca el precio más conveniente en tiendas chilenas para cada ítem de un lote de licitaciones, con links, y verifica los precios abriendo las páginas',
  phases: [
    { title: 'Buscar', detail: 'un agente por licitación busca precios por ítem con WebSearch' },
    { title: 'Verificar', detail: 'un escéptico abre los links y confirma precio, producto e IVA' },
  ],
}

const LOTE = args.lote  // [{codigo, nombre}]
const ARCHIVO = args.archivo
const HOY = args.hoy

const OPCION = {
  type: 'object',
  properties: {
    tienda: { type: 'string', description: 'tienda o vendedor (p. ej. "Lider (vende Librería X)", "Sodimac", "Dimerc")' },
    producto_mercado: { type: 'string', description: 'nombre del producto tal como aparece en la tienda' },
    url: { type: 'string', description: 'link directo a la ficha del producto, tal como apareció en la búsqueda o página abierta' },
    precio: { type: 'number', description: 'precio publicado en CLP (número, sin puntos)' },
    iva_incluido: { type: 'boolean', description: 'true si el precio publicado incluye IVA (lo normal en tiendas al público); false si dice neto o + IVA' },
    contenido: { type: 'string', description: 'qué trae ese precio (p. ej. "caja 100 un", "resma 500 hojas", "1 unidad")' },
    unidades_equivalentes: { type: 'number', description: 'cuántas UNIDADES DE LA LICITACIÓN cubre ese precio (p. ej. licitación pide "Unidad" de guante y la tienda vende caja de 100 → 100; licitación pide "Caja" de 100 y la tienda vende caja de 100 → 1; licitación pide "Resma" y la tienda vende pack de 5 resmas → 5)' },
    precio_unitario_neto: { type: 'number', description: 'precio / 1.19 si iva_incluido / unidades_equivalentes, redondeado a peso' },
    coincidencia: { type: 'string', enum: ['exacta', 'equivalente', 'aproximada'], description: 'exacta: mismo producto/marca/modelo pedido; equivalente: cumple la especificación con otra marca; aproximada: parecido pero difiere en algo relevante (medida, material, capacidad)' },
    nota: { type: 'string', description: 'diferencias, stock, despacho, vendedor de marketplace, precio desde, etc.' },
  },
  required: ['tienda', 'producto_mercado', 'url', 'precio', 'iva_incluido', 'unidades_equivalentes', 'precio_unitario_neto', 'coincidencia'],
}
const RESULTADO = {
  type: 'object',
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          linea: { type: 'integer' },
          producto: { type: 'string' },
          consulta: { type: 'string', description: 'búsquedas hechas' },
          opciones: { type: 'array', items: OPCION, description: 'hasta 3, de más barata a más cara (por precio_unitario_neto), priorizando exactas/equivalentes' },
          nota: { type: 'string', description: 'si no se encontró o hay algo que advertir' },
        },
        required: ['linea', 'producto', 'opciones'],
      },
    },
  },
  required: ['items'],
}
const VERIFICADO = {
  type: 'object',
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          linea: { type: 'integer' },
          producto: { type: 'string' },
          opciones: {
            type: 'array',
            items: { ...OPCION, properties: { ...OPCION.properties, verificado: { type: 'boolean', description: 'true si abriste la página y el precio y el producto coinciden' } }, required: [...OPCION.required, 'verificado'] },
          },
          nota: { type: 'string' },
        },
        required: ['linea', 'producto', 'opciones'],
      },
    },
    resumen: { type: 'string', description: 'qué se corrigió o eliminó' },
  },
  required: ['items', 'resumen'],
}

const REGLAS = `Reglas:
- Busca en el mercado CHILENO (tiendas .cl y Mercado Libre Chile): por ejemplo Lider, Falabella, Paris, Ripley, Sodimac, Easy, Construmart, Imperial, MTS, PC Factory, SP Digital, Microplay, Dimerc, Prisa, OfficeStore/Office Depot, Librería Nacional, Jumbo, Santa Isabel, Unimarc, distribuidores de insumos médicos y de aseo (p. ej. Medihelp, Dentalmarket, Tork/Elite distribuidores), mayoristas (Alvi, Mayorista 10) y fabricantes nacionales. Excluye productos usados, reacondicionados y envíos internacionales (AliExpress, Amazon US, Shein, Temu).
- Usa WebSearch en modo "standard" (pasa a "extended" solo si los resultados son pobres). Cuando el resultado no muestre el precio, abre la ficha con WebFetch. Haz 1–3 búsquedas por ítem como máximo.
- NUNCA inventes precios ni links: cada opción debe venir de un resultado de búsqueda o de una página que abriste en esta sesión, con su URL exacta. Si no encuentras nada confiable, deja "opciones" vacía y explica en "nota".
- Respeta la especificación del comprador (medidas, material, talla, capacidad, marca si la exige) y la UNIDAD de la licitación: convierte el precio a esa unidad con "unidades_equivalentes" y calcula precio_unitario_neto = precio / 1,19 (si incluye IVA) / unidades_equivalentes.
- Prefiere el precio más bajo entre productos exactos o equivalentes; incluye una opción "aproximada" solo si no hay equivalentes.
- Los precios de tiendas al público en Chile incluyen IVA salvo que digan "neto" o "+ IVA".
- Fecha de consulta: ${HOY}.`

function promptBuscar(l) {
  return `Eres un comprador experto en Chile. Busca, para CADA ítem de la licitación ${l.codigo} "${l.nombre}", los precios más convenientes del mercado chileno para comprarlo y revenderlo al Estado.
Los datos de la licitación (organismo, región, cierre) y sus ítems (linea, producto ONU, descripción del comprador, cantidad, unidad y ref_mediana = precio neto por unidad que el Estado pagó en OC por ese producto ONU, solo como referencia) están en el archivo JSON ${ARCHIVO}: es una lista; usa el elemento con "codigo" = "${l.codigo}". Léelo con Read o con python3 -I.

${REGLAS}

Devuelve un elemento en "items" por cada línea, con hasta 3 opciones ordenadas de menor a mayor precio_unitario_neto.`
}

function promptVerificar(l, r) {
  return `Eres un verificador ESCÉPTICO de precios. Otro agente buscó precios en tiendas chilenas para la licitación ${l.codigo} "${l.nombre}". Los ítems pedidos (cantidad, unidad y especificación) están en ${ARCHIVO}, elemento con "codigo" = "${l.codigo}" (léelo con Read o python3 -I).

Resultado a verificar:
${JSON.stringify(r.items, null, 1)}

Para CADA opción: abre su URL con WebFetch y confirma que (1) la página existe y es de una tienda chilena, (2) el producto coincide con lo pedido (corrige "coincidencia" si hace falta), (3) el precio publicado es el que se informó (corrígelo si cambió) y si incluye IVA, (4) "unidades_equivalentes" y "precio_unitario_neto" están bien calculados para la unidad de la licitación (recalcula: precio / 1,19 si incluye IVA / unidades_equivalentes). Marca verificado=true solo si abriste la página y coincide. Si la página no carga (bloqueos, JavaScript), deja la opción con verificado=false y explica en "nota". ELIMINA las opciones con URL inventada o rota, de otro país o que no corresponden al producto. Reordena de menor a mayor precio_unitario_neto. Si un ítem quedó sin opciones y ves una alternativa clara con una búsqueda rápida, puedes agregarla (con verificado=true solo si abriste su página).

${REGLAS}`
}

const resultados = await pipeline(
  LOTE,
  (l) => agent(promptBuscar(l), { label: `buscar:${l.codigo}`, phase: 'Buscar', schema: RESULTADO }),
  async (r, l) => {
    if (!r) return null
    const v = await agent(promptVerificar(l, r), { label: `verificar:${l.codigo}`, phase: 'Verificar', schema: VERIFICADO })
    return { codigo: l.codigo, nombre: l.nombre, fecha_consulta: HOY, items: (v || r).items, verificacion: v ? v.resumen : 'sin verificar' }
  },
)
const ok = resultados.filter(Boolean)
log(`${ok.length}/${LOTE.length} licitaciones con precios`)
return { licitaciones: ok }
