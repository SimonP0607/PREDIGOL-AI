# PM-12-05 · El LAB de Intelligence, la participación y la analítica espacial dentro de sus límites (IA-159)

Plan Maestro PM, ola 6 (OP-41, OP-48, OP-53, OP-54). Nada de esto corre en el servidor ni llega a un lector: el LAB trabaja en el
portátil sobre la exportación de solo lectura (PM-12-02, `scripts/lab_export.py`) y sobre los bancos etiquetados propios. Un mal
resultado del LAB nunca cambia una regla de producción.

**Estado: pendiente-dueño, consulta DM-08** para la parte de OP-53 que usaría el conjunto de Wyscout y para todo OP-54. Lo demás queda
con sus límites escritos y con la regla que los vigila.

## 1. Estado de cada línea (21-nov-2026)

| Línea | Estado | Límite vigente | Siguiente paso |
|---|---|---|---|
| OP-41 · LAB de Intelligence (NLI y embeddings en sombra, enlace por trigramas, clasificador de inyección, Inspect AI, citas nativas, referencia de crónicas) | **en curso** (sin experimento todavía) | En el portátil, contra los bancos propios (battery-v4 y conjuntos de referencia). Nada llega al paquete de Intelligence, a un prompt ni a producción. Un modelo o biblioteca descargado entra por la regla de alta de proveedores (DOC-007 §3). Hoy en el repositorio: `pg_trgm` y `unaccent` (migración 0145); sin pgvector, NLI, embeddings, Prompt Guard ni Inspect AI | Registrar el protocolo (hipótesis, banco, métrica y umbral) en el sobre del LAB **antes** de medir |
| OP-48 · Participación y audio («¿Quién gana?», «escuchar la crónica») | **cerrada** | Sin base de lectores suficiente; la capa pública sigue cerrada (DM-12, recomendación A); la crónica no está publicada (DM-14) | Reabrir con base de lectores medida y la crónica publicada |
| OP-53 · Analítica espacial y demostrador histórico con datos abiertos | **esperando dictamen** (parte Wyscout) | El conjunto de Wyscout (Pappalardo et al.) **no se usa** hasta el dictamen: figshare y el artículo dicen CC BY 4.0, el catálogo D4Science dice «Non-commercial only», y los datos los produjo Wyscout (hoy Hudl), que los vende. El resto de OP-53 puede correr solo con un conjunto `permitido_lab` del registro, con atribución y sin publicar: hoy **ninguno espacial** está aprobado | Dueño: consulta DM-08 («Dataset de Wyscout y vías con dictamen»). Mientras, proponer un conjunto abierto y pasarlo por `check` |
| OP-54 · Vías con dictamen previo (muestra de BSD con xG por tiro, anotación manual de tiros) | **esperando dictamen** | No empieza: ni descarga, ni anotación, ni medida | Dueño: consulta DM-08 |

Decisión del dueño anotada: DM-08 (enviar los siete asuntos al abogado) aprobada según la recomendación el 19-nov-2026; **la consulta no
está hecha**. DM-12 (capa pública cerrada) aprobada. No se simula ninguna respuesta del abogado.

## 2. La regla que lo vigila: «origen antes que etiqueta»

`backend/scripts/lab_datasets.py` (`lab-datasets-v1`, solo biblioteca estándar: corre en el portátil tal cual):

- **registro cerrado** (`DATASETS`) de los conjuntos externos que el LAB podría cargar; uno que no está se rechaza;
- solo se carga uno en estado `permitido_lab`, y ese estado exige el **productor** del dato declarado (no solo quien publica el
  archivo), que sus términos **permitan reutilizar**, la fuente de la licencia leída con fecha y **ningún dictamen pendiente**. Una
  etiqueta abierta (CC0, CC BY, MIT) sobre un origen restringido no basta (DOC-007 §2 y §4.4);
- hoy: `permitido_lab` solo los bancos propios; `esperando_dictamen` (DM-08) Wyscout, BSD y la anotación manual; `no_usar` los cinco
  grupos de DOC-007 §4.4.

```
python scripts/lab_datasets.py list                       # líneas, conjuntos, estado y motivo
python scripts/lab_datasets.py check wyscout-pappalardo-2019   # sale con 1: esperando dictamen DM-08
```

Un experimento del LAB llama a `check` antes de leer un conjunto externo. Dar de alta uno nuevo es un PR que cambia la lista y pasa
`tests/unit/test_lab_datasets.py`.

## 3. Qué falta para cerrar

- Respuesta escrita del abogado (DM-08) sobre Wyscout y las vías de OP-54, anotada por el dueño en este documento y en el registro.
- OP-41: el protocolo registrado y su veredicto (pasa, no pasa o insuficiente).
- Cierre de la ficha: veredicto de cada línea y decisión del dueño anotados.
