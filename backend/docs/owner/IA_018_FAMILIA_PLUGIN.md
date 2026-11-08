# IA-018 · Familia de mercado como plug-in (`family-plugin-v1`)

Fecha: 7 nov 2026. Estado: **en el código, sin desplegar, en SOMBRA**. Sin migración ni interruptor. Nada que decide lo importa y no hay ninguna familia instalada (`fbi.plugins.registry.INSTALLED` está vacío). Lo vigilan `tests/unit/test_family_plugin.py`, `tests/unit/test_family_plugin_isolation.py` y `tests/integration/test_family_plugin_template.py`.

## Qué es

Una familia es **una sola entrada** (`fbi.plugins.family.FamilyPlugin`) que cada capa lee por referencia a lo que ya tiene: apuestas de la taxonomía y sus claves del catálogo, estado, modelo y proveedor de distribución, ranuras del calibrador (mercado, modelo), regla de liquidación, puerta de ventaja (`edge-gate-v1`) y su adaptador de `decision-v2` (`MarketFamily`). El registro (`fbi.plugins.registry`) la comprueba contra todas las capas y entrega a cada consumidor su vista: las familias que toman `decision-v2` y su replay, y el proveedor de correlación que toma la cartera. **El núcleo no se edita**: las familias se le pasan.

Estados: `NOT_MODELABLE` → `CANDIDATE` → `RESEARCH` (las palabras de la taxonomía) → `SHADOW` (se calcula y se juzga; nunca pasa de ABSTAIN) → `ACTIVE`. A `ACTIVE` solo se llega con `promote`: **calibrador CHAMPION y ventaja validada en cada mercado**, y solo desde SHADOW. Una entrada que diga ACTIVE sin ese registro no se puede construir.

Ejemplo trabajado: `fbi/plugins/_template/` — **TEAM_TOTALS** (goles de un equipo, apuestas 16 y 17, claves `OU_HOME` / `OU_AWAY`) sumado sobre la distribución conjunta de `sim-v1` del Dixon-Coles en vigor. SHADOW, con la promoción prohibida (`activatable=False`), no instalado.

## Lista para añadir una familia

1. **Datos.** Las apuestas están en `fbi.odds.quote_taxonomy`, **extraídas** y no `NOT_MODELABLE`; el catálogo deriva sus claves (`market_key_for`) y una regla de `fbi.market.rules` las liquida (liquidable). Ninguna clave es de otra familia.
2. **Modelo.** Copia `_template/` a `fbi/plugins/<nombre>/`. Nombre y versión del modelo; lectura *as-of* (nada posterior al momento, nunca después del saque); proveedor de distribución si da dependencias. Fuera de los paquetes de modelo: **la huella `mc9a7bec97ca` no cambia**.
3. **Calibración.** Nada que escribir: las ranuras son (clave, modelo) de `intel.calibrators`. Sin campeón, `decision-v2` se abstiene.
4. **Evaluación.** En SHADOW: `Registry().register(...)` sin errores; el replay (`replay_day(families=registry.decision_families())`) y la cartera (`estimate(joint=registry.joint_provider(...))`) la leen; pruebas propias como las del ejemplo.
5. **Puerta.** `promote(...)` con calibrador CHAMPION y `edge-gate-v1` validado en **todos** sus mercados, por decisión del dueño (`promote` comprueba y devuelve la entrada ACTIVE; no escribe nada). Solo entonces se añade a `INSTALLED` y se decide quién la lee (las pruebas de aislamiento fallan hasta entonces).

Vuelta atrás: quitar la entrada de `INSTALLED` (o el paquete). Nada se migra ni se escribe.
