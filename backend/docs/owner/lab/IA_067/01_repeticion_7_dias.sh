#!/usr/bin/env bash
# IA-067 · 01 · decision-v2.1 (precio del libro + edad por horizonte 195/75/45 min) frente a decision-v2.0, día a día. SOLO LECTURA.
# Tras el despliegue, en el servidor: la orden del propio código, dentro del worker, un día detrás de otro (cada día tarda de 1 a 4 min).
# La conexión es de solo lectura y cada sentencia tiene 95 s (lo pone la orden al leer el libro). Las salidas quedan en /tmp/lab_ia067.
# Cambia los días para otra ventana (la de la medición del 16-nov-2026: del 9 al 15-nov, días de Bogotá).
set -u
L=/tmp/lab_ia067; mkdir -p "$L"
for d in 2026-11-09 2026-11-10 2026-11-11 2026-11-12 2026-11-13 2026-11-14 2026-11-15; do
  timeout 1500 docker exec -i -w /app predigol-worker python -m scripts.ia_decision_v2 replay --day "$d" --rules decision-v2.1 \
    --against decision-v2.0 --against decision-v2.0:book --json > "$L/out_$d.json" 2> "$L/err_$d.txt"
done
# Lo que se lee de cada informe: price.without_age (precio sin edad: tiene que ser 0), price.states.by_source.book (estados del precio del
# libro, por franja: antiguo / con precio ≤ 1 %), y versus (cuántas decisiones cambian de estado, de cuál a cuál, en qué etapa y cuántas
# llegan a RECOMMENDED). El registro del worker puede escribir líneas de depuración en la misma salida: el informe es lo que va desde la
# primera línea que empieza por «{» (sed -n '/^{/,$p' "$L/out_<día>.json"). Borra "$L" al terminar.
