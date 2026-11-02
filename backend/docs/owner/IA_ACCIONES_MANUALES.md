# Acciones manuales del dueño · Plan Maestro IA

Fecha: 25 oct 2026 (la sección de `step_keys.sh` se añadió el 26 oct 2026 y se quitó la ventana horaria el 26 oct 2026 a las 23:00 UTC por orden del dueño; **las acciones 6 y 7 se hicieron el 26 oct 2026 a las 23:44 UTC**). Fuente: secciones 45 y 46 del Plan Maestro IA (aprobado). Son **16 acciones**, todas tuyas: yo no entro en la Console de Anthropic ni toco claves.

**Estas 16 no son las tareas del plan de seguridad** (esas se numeran aparte en `ESTADO_EJECUCION_SEGURIDAD.md`). Aquí «acción 7» es siempre la 7 del Plan Maestro IA.

## La regla de las claves

**Una clave nunca se pega en el chat**, ni en Git, ni en un prompt, ni en la memoria de Claude, ni en una tabla, ni en la web. Se guarda en tu gestor de contraseñas y se copia **al servidor** en el fichero de entorno de la aplicación (`/etc/predigol/app.env`; tras la fase S8 del plan de seguridad será `worker.env`). Yo solo leo los **nombres** de las variables, nunca sus valores.

Para ponerla sin que se vea en pantalla ni quede en el historial de la terminal:

```bash
ssh predigol
grep -c '^FBI_AI_KEY_ANTHROPIC_LAB=' /etc/predigol/app.env   # debe salir 0; si sale 1, edita esa línea con nano en vez de añadir otra
read -rs -p 'Clave worker-lab (no se ve al pegarla): ' K; echo
printf 'FBI_AI_KEY_ANTHROPIC_LAB=%s\n' "$K" >> /etc/predigol/app.env; unset K
```

No dejes copias `.bak` del fichero con una clave nueva. El fichero sigue siendo de `root` con permisos 600.

## Cuándo y en qué orden

Los valores de abajo son los definitivos del plan. Las acciones 6 y 7 reinician la API y el worker unos segundos (los dos leen `app.env`), así que **cuentan como tocar producción**, pero **ya no hay ventana horaria** (orden del dueño, 26 oct 2026 23:00 UTC): se pueden hacer a cualquier hora y yo te aviso cuando toque. Lo que protege al servidor no es el reloj sino el propio script: toma el candado del despliegue (nadie más despliega ni reinicia a la vez), espera a que no haya escrituras largas abiertas (`fixtures_sync`, la corrida nocturna), repite esa comprobación justo antes de reiniciar y repone la copia si la API o el worker no quedan sanos. Lo que sí puedes hacer ya, sin tocar el servidor, es todo lo de la Console.

| Cuándo | Acciones | Qué desbloquea |
| --- | --- | --- |
| **Ahora** (Console, unos 15 min) | 1, 2, 3, 4, 5 | Las claves y los workspaces que necesitan las pruebas del LAB. **El gate A espera a la 3 y a la 5.** |
| **HECHAS el 26 oct a las 23:44 UTC** | 6 y 7 | La clave de producción en su workspace y la clave del LAB con los tres sobres (185, 15 y 35). El gate A esperaba a la 7: ya no la espera. |
| Después | 8, 9, 10 (topes en la Console), 11 (48 h después de la 6), 12, 13, 14 | La red de seguridad de la Console y la conciliación |
| Al empezar la fase 3 | 15 | **El arranque de la sombra espera a la 15** |
| En la fase 9 | 16 | Vuelve el LAB a su tamaño de régimen |

**Estado a 25 oct 08:00 UTC** (lo que puedo ver desde el servidor, por nombres de variables; la Console solo la ves tú): no hay `FBI_AI_KEY_ANTHROPIC_LAB` ni `FBI_AI_LAB_MONTHLY_BUDGET_USD` ni `FBI_AI_EXA_MONTHLY_BUDGET_USD`; `FBI_AI_MONTHLY_BUDGET_USD` vale 180 (el plan pide 185) y `FBI_AI_DAILY_BUDGET_USD` y `FBI_AI_DAILY_TARGET_USD` valen 6,00. Ninguna de las 16 está marcada como hecha.

**Estado a 27 oct 00:15 UTC.** Las acciones 6 y 7 están **hechas y comprobadas en el servidor** (26 oct, 23:44:52 UTC): las dos claves instaladas y aceptadas por Anthropic con la consulta que no gasta, `FBI_AI_KEY_ANTHROPIC_LAB` añadida y `FBI_AI_KEY_ANTHROPIC` sustituida, los tres sobres puestos (185, 15 y 35), API y worker recreados y sanos, 0 fugas; la clave antigua sigue guardada en `app.env.before-ia-keys-20261026T234019Z` (de root y 600) hasta la acción 11. Las acciones 2 a 5 las das por hechas y desde el servidor no se ven; la prueba indirecta es que Anthropic acepta las dos claves y que las sondas del LAB corren con la del LAB. Las 8 a 16 siguen pendientes (la 15 no hasta empezar la fase 3).

**Lo único que me falta para cerrar la comprobación de las claves es tuyo y es solo mirar:** en Cost o en Usage de la Console, con el filtro de `worker-lab` y el de `worker-prod`, que cada clave suma en su workspace (PREDIGOL-LAB y PREDIGOL). El panel va con horas de retraso («Data as of …»): tu primera mirada, el 27 oct a las 00:06 UTC, enseñaba datos de las 22:51 UTC del 26 oct, anteriores a las claves, así que US$ 0,00 era lo esperado y no un fallo. Vuelve a mirar pasadas unas horas: en `worker-lab` deberían salir ≈ US$ 0,03 de las sondas y, cuando cierren los dos lotes de Anthropic, ≈ US$ 10 más; `worker-prod` sale con la primera llamada de producción con la clave nueva. Tampoco hace falta esperar al panel: Settings → API keys enseña el último uso de cada clave (si la columna está).

## Las acciones 6 y 7 con un solo comando (`step_keys.sh`), a cualquier hora

**Hecho el 26 oct 2026 a las 23:44 UTC (tercera ejecución, sin ventana).** Lo que sigue se conserva para cuando haya que cambiar una clave (rotación) o repetirlo.

La entrega de las fases 0 y 1 lleva un script que hace la 6 y la 7 juntas sin que ninguna clave se vea en pantalla, quede en el historial de la terminal, en un registro o en el chat. Va **después** del despliegue y de su verificación, a cualquier hora (sin ventana), y yo te aviso cuando sea el momento. Se ejecuta desde tu ordenador, en una terminal (sin terminal se niega):

```bash
ssh -t predigol /root/releases/<sello>-ia-p01/step_keys.sh
```

`<sello>` es el de la entrega; hoy la carpeta es `20261026T1955Z-ia-p01` y yo te escribo la ruta completa al avisarte. Antes de ese momento tienes que tener hechas las acciones 2, 3, 4 y 5 y las dos claves (`worker-lab` y `worker-prod`) a mano en tu gestor de contraseñas. Si hoy solo tienes una, escribe `DEJAR` en la otra y se queda como está; esa se pone después, volviendo a ejecutar el script (no hay límite de horario) o con el procedimiento manual de las acciones 6 y 7 de más abajo.

Qué verás y qué hacer, en orden (el script escribe sin tildes a propósito: la consola de Windows las muestra mal):

1. **Un resumen** de lo que hay ahora en el fichero, solo con nombres (una clave se dice `set` o `empty`, nunca se muestra). Antes de pedirte nada comprueba que la versión desplegada es la de la IA, que la IA sigue en sombra y que el servidor está tranquilo (tarda como un minuto: **no pulses ninguna tecla hasta ver «CLAVE 1 de 2»**; lo que se teclee antes se descarta); si hay una escritura larga abierta espera (hasta 20 intentos, cerca de media hora) y no te pide nada hasta entonces.
2. **«CLAVE 1 de 2»**, la del LAB (`worker-lab`): pégala; no se ve al pegarla. Te dice cuántos caracteres recibió (una clave de Anthropic tiene del orden de 100) y si empieza por `sk-ant-`; comprueba que tiene forma de clave y que Anthropic la acepta con una consulta que no gasta nada; tienes tres intentos. Para dejarla como está escribe `DEJAR`: un Intro vacío **no** vale (se te vuelve a pedir, para que un Intro de más no deje la clave sin poner).
3. **«CLAVE 2 de 2»**, la de producción (`worker-prod`), igual. Las dos tienen que ser distintas.
4. **Lo que va a hacer, por nombres**, y la pregunta final: escribe `SI` en mayúsculas para aplicarlo; cualquier otra cosa cancela y no toca nada.
5. **El cambio.** Guarda una copia fechada del fichero (`app.env.before-ia-keys-<sello>`, de root y 600; conserva la clave **antigua** hasta que la desactives en la acción 11), escribe `FBI_AI_KEY_ANTHROPIC_LAB`, `FBI_AI_KEY_ANTHROPIC`, `FBI_AI_MONTHLY_BUDGET_USD=185`, `FBI_AI_LAB_MONTHLY_BUDGET_USD=15` y `FBI_AI_EXA_MONTHLY_BUDGET_USD=35` de forma atómica, comprueba que solo cambiaría la configuración de la API y del worker, vuelve a mirar que el servidor está tranquilo y reinicia **solo esos dos** (unos segundos). Si en 4 minutos no están sanos, **repone la copia** y los vuelve a crear.
6. **Las comprobaciones**, sin mostrar ningún valor: que la base de datos, la web y Caddy siguen siendo los mismos contenedores, que el worker tiene las variables, el estado de la sonda de la IA (`ia_probe status`, que no llama a ningún proveedor) y la cuenta de fugas, que tiene que ser 0 (busca los valores de las claves en los registros de la entrega y de los contenedores).

Si sale «LISTO», escríbeme una sola palabra en el chat (por ejemplo «hecho»); yo leo el resto desde el servidor. **Nunca pegues una clave en el chat**, ni una captura que la muestre. Salidas del script: 0 hecho (o nada que hacer), 1 se negó antes de tocar nada, 2 tocó el fichero y volvió atrás, 3 hecho con algo que mirar. En los tres últimos casos cuéntame lo que dice la pantalla (nunca una clave): no se revierte nada más sin que lo hablemos.

Para comprobarlo tú: en Usage o en Cost, con `worker-prod` en el selector, aparecen peticiones en cuanto el panel se ponga al día (va con retraso de horas, mira la fecha de «Data as of») y la clave antigua deja de sumar; Operación → Costes muestra 185, 15 y 35. La clave antigua **no** se desactiva hoy: es la acción 11, 48 horas después y solo si Usage confirma 0 peticiones suyas (nunca «Delete»).

## Cómo encontrar cada página

No he podido verificar las etiquetas del menú de la Console (Keys & access, Spending, Usage, Security & data), así que van las direcciones directas:

- **Keys & access:** API keys (`platform.claude.com/settings/keys`) y Members.
- **Spending:** Billing (`platform.claude.com/settings/billing`) y Workspaces (`platform.claude.com/settings/workspaces`).
- **Usage:** Usage (`platform.claude.com/usage`) y Cost (`platform.claude.com/cost`).
- **Security & data:** Data retention (`platform.claude.com/settings/privacy`).

---

## Acción 1 · De dónde viene el gasto de octubre

- **DÓNDE:** Cost (selector «Workspace» y mes actual) y Usage (selector «API key»).
- **QUÉ HACER:** anotar de qué workspace y de qué clave viene el gasto. Si hay gasto de otro uso (por ejemplo, Claude Code con clave de API), dale su propio workspace con su propio tope y suma esa cantidad al tope de la organización en la acción 8.
- **VALOR:** nada en PrediGol.
- **CÓMO VERIFICAR:** sabes si producción gasta en Default o en PREDIGOL, y ningún otro uso se come de los 200 USD de PrediGol.
- **QUÉ BLOQUEA:** nada técnico. Condiciona el valor de la acción 8.

## Acción 2 · El workspace PREDIGOL

- **DÓNDE:** Workspaces.
- **QUÉ HACER:** si PREDIGOL no existe: «Create workspace» → nombre `PREDIGOL` → un color → «Create workspace». Solo un Admin de la organización puede. No toques el workspace Default: no admite tope de gasto y no se puede borrar.
- **VALOR:** nombre exacto `PREDIGOL` (es el nombre que el libro de cuentas de la IA guarda en `ai.usage.workspace`).
- **CÓMO VERIFICAR:** PREDIGOL aparece en la lista.
- **QUÉ BLOQUEA:** nada técnico. Las acciones 4 y 9 lo necesitan.

## Acción 3 · El workspace PREDIGOL-LAB

- **DÓNDE:** Workspaces.
- **QUÉ HACER:** «Create workspace» → nombre `PREDIGOL-LAB` → otro color → «Create workspace». No archives ningún workspace: archivar no se deshace y archiva sus claves.
- **VALOR:** nombre exacto `PREDIGOL-LAB`.
- **CÓMO VERIFICAR:** PREDIGOL-LAB aparece en la lista.
- **QUÉ BLOQUEA:** **el gate A** y todas las pruebas del LAB.

## Acción 4 · La clave `worker-prod`

- **DÓNDE:** API keys, con PREDIGOL elegido en el selector «Workspace».
- **QUÉ HACER:** «Create key» → nombre `worker-prod` → si te ofrece cuenta de servicio, úsala → caducidad: ninguna, con rotación manual cada 6 meses → «Create key». La clave (empieza por `sk-ant-`) se muestra **una sola vez**: guárdala en tu gestor de contraseñas.
- **VALOR:** nombre `worker-prod`.
- **CÓMO VERIFICAR:** la clave aparece en la lista de PREDIGOL.
- **QUÉ BLOQUEA:** nada técnico. Sin ella, el tope de 190 USD de la Console no protege a producción (la protección interna del presupuesto sigue funcionando).

## Acción 5 · La clave `worker-lab`

- **DÓNDE:** API keys, con PREDIGOL-LAB elegido en el selector.
- **QUÉ HACER:** «Create key» → nombre `worker-lab`, igual que la anterior. Al gestor de contraseñas.
- **VALOR:** nombre `worker-lab`.
- **CÓMO VERIFICAR:** aparece en la lista de PREDIGOL-LAB.
- **QUÉ BLOQUEA:** **el gate A** y las pruebas del LAB.

## Acción 6 · La clave de producción en el servidor

- **ESTADO:** **HECHA el 26 oct 2026 a las 23:44:52 UTC** (con `step_keys.sh`, tercera ejecución). Falta solo tu mirada de Usage/Cost de más abajo.
- **DÓNDE:** servidor, por SSH con tu usuario; fichero `/etc/predigol/app.env`.
- **QUÉ HACER:** poner en `FBI_AI_KEY_ANTHROPIC` la clave `worker-prod` (edita la línea que ya existe con `nano`; no añadas otra). Reinicia con el procedimiento de siempre: `predigolctl up` (si la terminal no lo encuentra: `/opt/predigol/backend/deploy/vps/bin/predigolctl up`). No toques otras variables que las de esta lista y no dejes copias `.bak` con la clave nueva.
- **VALOR:** `FBI_AI_KEY_ANTHROPIC` = la clave `worker-prod`.
- **CÓMO VERIFICAR:** en Usage o en Cost, con `worker-prod` en el selector, aparecen peticiones en cuanto el panel se ponga al día (va con retraso de horas, mira la fecha de «Data as of»; el ciclo de producción corre cada 15 minutos) y la clave antigua deja de sumar.
- **QUÉ BLOQUEA:** nada técnico. Condiciona las acciones 9 y 11.

## Acción 7 · La clave del LAB y los tres sobres

- **ESTADO:** **HECHA el 26 oct 2026 a las 23:44:52 UTC** (con `step_keys.sh`): `ia_probe status` dice clave del LAB puesta, sobre del LAB 15 con 15,0000 disponibles y 0 bloqueos; las sondas de caché y de esquema pasan con ella. Falta solo tu mirada de Usage/Cost bajo PREDIGOL-LAB.
- **DÓNDE:** servidor, cuando esté desplegado el código de la fase 0 (o justo antes, en el mismo momento: el código viejo ignora las variables nuevas).
- **QUÉ HACER:** añadir `FBI_AI_KEY_ANTHROPIC_LAB` con el comando de arriba (la clave no se ve); cambiar `FBI_AI_MONTHLY_BUDGET_USD` de 180 a 185 (esa línea ya existe: edítala); añadir `FBI_AI_LAB_MONTHLY_BUDGET_USD=15` y `FBI_AI_EXA_MONTHLY_BUDGET_USD=35`. Reinicia el worker con `predigolctl up`.

  ```bash
  sed -i 's/^FBI_AI_MONTHLY_BUDGET_USD=.*/FBI_AI_MONTHLY_BUDGET_USD=185/' /etc/predigol/app.env
  printf 'FBI_AI_LAB_MONTHLY_BUDGET_USD=15\nFBI_AI_EXA_MONTHLY_BUDGET_USD=35\n' >> /etc/predigol/app.env
  ```

- **VALOR:** `FBI_AI_KEY_ANTHROPIC_LAB` = la clave `worker-lab`; `FBI_AI_MONTHLY_BUDGET_USD=185`; `FBI_AI_LAB_MONTHLY_BUDGET_USD=15`; `FBI_AI_EXA_MONTHLY_BUDGET_USD=35`.
- **CÓMO VERIFICAR:** Operación → Costes muestra 185, 15 y 35; yo lo compruebo además con `python -m scripts.ia_probe status` dentro del worker (dice si hay clave LAB y qué sobres ve, nunca la clave); y cuando corran las pruebas del LAB aparecen en Usage bajo PREDIGOL-LAB.
- **QUÉ BLOQUEA:** **el gate A**: sin la clave LAB y sus sobres no corren las sondas ni la prueba de equivalencia.

## Acción 8 · Tope de la organización

- **DÓNDE:** Billing → Spend limits → «Adjust limit» (o «Set limit»).
- **QUÉ HACER:** 200 USD al mes, más lo del otro uso si la acción 1 lo encontró. No puede superar el tope del tier Start (500).
- **VALOR:** `200`.
- **CÓMO VERIFICAR:** Billing muestra 200, o 200 más el otro uso.
- **QUÉ BLOQUEA:** nada técnico.

## Acción 9 · Tope de PREDIGOL

- **DÓNDE:** Workspaces → PREDIGOL → «Spend limits».
- **QUÉ HACER:** en «Monthly limit», «Change limit»: `190`. En «Email notification», «+ Add notification» con `95`, `133`, `162` y `181` (el 50, 70, 85 y 95 % de 190).
- **VALOR:** 190 y los cuatro avisos.
- **CÓMO VERIFICAR:** el panel muestra 190 y los cuatro avisos.
- **QUÉ BLOQUEA:** nada técnico. Si la Console corta antes que el presupuesto interno, el sistema lo registra como `EXHAUSTED` y no insiste.

## Acción 10 · Tope de PREDIGOL-LAB

- **DÓNDE:** Workspaces → PREDIGOL-LAB → «Spend limits».
- **QUÉ HACER:** «Monthly limit»: `20`; avisos en `10`, `14`, `17` y `19`.
- **VALOR:** 20 y los cuatro avisos.
- **CÓMO VERIFICAR:** el panel muestra 20 y los cuatro avisos.
- **QUÉ BLOQUEA:** nada técnico.

## Acción 11 · Desactivar la clave antigua

- **DÓNDE:** API keys, 48 h después de la acción 6.
- **QUÉ HACER:** si Usage confirma 0 peticiones de la clave antigua: «Disable». **Nunca «Delete»**: la archiva para siempre y no se puede volver.
- **VALOR:** nada.
- **CÓMO VERIFICAR:** la clave antigua no suma gasto y producción sigue respondiendo.
- **QUÉ BLOQUEA:** nada técnico.

## Acción 12 · Usage y Cost

- **DÓNDE:** Usage y Cost.
- **QUÉ HACER:** revisa tokens, modelo, la tasa de caché (gráfica «Rate Limit Use + Caching – Input Tokens»), gasto por workspace y ritmo. **Exporta el CSV a fin de mes** para la conciliación. Al promover una familia (fase 7), comprueba que su gasto pasa a PREDIGOL.
- **VALOR:** nada.
- **CÓMO VERIFICAR:** las cifras cuadran con Operación → Costes (diferencia < 5 %); el CSV se compara con `python -m scripts.ia_reconcile`.
- **QUÉ BLOQUEA:** la conciliación de un mes del gate final. Antes, nada.

## Acción 13 · Retención de datos

- **DÓNDE:** Data retention.
- **QUÉ HACER:** solo mirar: deja «Standard data retention» como está. No actives «HIPAA compliance»: es permanente. La retención cero (ZDR) requiere hablar con ventas. Fable 5.1 exige retención de 30 días en sus peticiones: úsalo sin datos personales.
- **VALOR:** nada.
- **CÓMO VERIFICAR:** nada cambió.
- **QUÉ BLOQUEA:** nada.

## Acción 14 · Miembros y seguridad de tu cuenta

- **DÓNDE:** Members y la seguridad de tu cuenta de Anthropic.
- **QUÉ HACER:** solo tú como Admin; MFA activa en la cuenta de Anthropic. No añadas miembros ni crees claves de Admin API (no está disponible para cuentas individuales).
- **VALOR:** nada.
- **CÓMO VERIFICAR:** Members lista solo tu usuario como Admin.
- **QUÉ BLOQUEA:** nada técnico (la MFA también la pide el plan de seguridad para esa cuenta).

## Acción 15 · Al empezar la fase 3: el LAB crece para la sombra

- **DÓNDE:** Workspaces → PREDIGOL-LAB → «Spend limits»; y el servidor.
- **QUÉ HACER:** «Monthly limit»: `60`; avisos en `30`, `42`, `51` y `57`. En el servidor, `FBI_AI_LAB_MONTHLY_BUDGET_USD=55` (la línea ya existe: edítala) y reinicio del worker.
- **VALOR:** 60 en la Console y 55 en el servidor.
- **CÓMO VERIFICAR:** el panel muestra 60 y Operación → Costes, 55.
- **QUÉ BLOQUEA:** **el arranque de la sombra** (fase 3). Te lo pediré cuando el gate A haya pasado.

## Acción 16 · En la fase 9: el LAB vuelve a su tamaño de régimen

- **DÓNDE:** Workspaces → PREDIGOL-LAB → «Spend limits»; y el servidor.
- **QUÉ HACER:** «Monthly limit»: `20`; avisos en `10`, `14`, `17` y `19`. En el servidor, `FBI_AI_LAB_MONTHLY_BUDGET_USD=15` y reinicio del worker.
- **VALOR:** 20 en la Console y 15 en el servidor.
- **CÓMO VERIFICAR:** el panel muestra 20 y Operación → Costes, 15.
- **QUÉ BLOQUEA:** nada técnico (el gasto de la fase 9 sin reducir el LAB se sale del sobre conjunto de 190).

---

## Lo que no hace falta en la Console

- **Caché de prompts:** se implementa en las peticiones y la Console solo la mide.
- **Batch:** lo gestiona el backend por API.
- **Managed Agents, environments, memory stores, vaults y skills:** no se crean.
- **Límites de ritmo:** la hora punta medida fue de 447 llamadas (≈ 8 por minuto de media) frente a 1.000 por minuto permitidas, así que no hacen falta.

## Tus firmas

Los gates C, D, E y F llevan tu firma: te daré el informe reproducible de cada uno y la fila de `intel.promotions` la escribe una orden que solo ejecutas tú. Un gate no se aprueba por una frase: pasa con evidencia o no pasa.
