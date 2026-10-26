# A16 · El gate del bloque A: QA, prueba real y ensayo

Plan Maestro UX, fase A16 (secciones 45 y 49; gate **READY FOR PAID USER**). A16 no añade nada al producto: comprueba,
con pruebas, que PrediGol puede recibir al primer cliente de pago. Tiene tres partes: **las 15 líneas del gate**, cada una
con su prueba; **la prueba real** de 16 pasos que haces tú con una cuenta que no es de administrador (P10); y **el ensayo**
con una persona que no conoce PrediGol (P11). Lo que salga de esas pruebas se arregla, y solo eso.

**Hoy: 1 de 15 líneas en verde. LISTO PARA COBRAR = NO.** No es un fallo de A16: las otras 14 esperan a que lo construido
llegue a producción y a tareas de fuera (el abogado, el plan de seguridad y tú). El detalle está en
`HOJA_GATE_A16.md`.

## 1. Lo que A16 ya hizo (en QA, sin tocar producción)

- **El recorrido entero de un cliente nuevo, automático y en QA** (`web/e2e/journey.spec.ts`): una cuenta que tú invitas
  desde la consola recorre los pasos 1 a 14 de la prueba real —invitación, activación, consentimientos, bienvenida
  cronometrada, Inicio, un partido, Picks, un parlay, Mis picks, el perfil con la copia de sus datos, un mensaje de soporte
  respondido, salir, entrar y recuperar la contraseña— y al final se borra. Corre en un teléfono de 390 px **con el motor
  de Android y con el del iPhone**. Los pasos 15 (teléfono real) y 16 (app instalada) son tuyos: QA no tiene teléfonos.
  Resultado en la sección 4.
- **Un arreglo que el recorrido encontró:** al tocar «Ver mi mensaje» justo después de que PrediGol respondiera, la
  página seguía diciendo «Esperando respuesta de PrediGol» hasta un minuto (lo tenía guardado). Ahora Ayuda y la página de
  un mensaje se leen de nuevo cada vez que se abren. Es la única línea de producto que cambia en A16.
- **Las tres hojas**, listas para cuando toque: `HOJA_GATE_A16.md` (las 15 líneas, su prueba y qué falta),
  `PRUEBA_REAL_A16.md` (tus 16 pasos, con lo que compruebo yo por lecturas sin ver datos personales) y
  `ENSAYO_PERSONA_NUEVA_A16.md` (las 11 preguntas, el cronómetro y cuándo se aprueba).

## 2. Lo que espera, y a quién

| Qué | Quién | Para qué líneas |
| --- | --- | --- |
| Desplegar A2…A15, una por noche (A2 va el 27-oct) | Yo, en las ventanas libres | Todas menos G1 |
| P4 (abierta), P5 (abogado), P1 (Sentry), P2 y P3 (correo), P14 (avisos), P6 y P7 (membresía y WhatsApp), P9 (transparencia) | Tú, de una en una, cuando sirvan | G3, G5–G7, G9, G10, G12 |
| El gate del plan de seguridad, con P13 (copias fuera del servidor) y P15 (acceso de administración separado) | El plan de seguridad y tú | G2, G13 |
| La prueba real (P10) y el ensayo (P11) | Tú y una persona nueva | G15, G8 |

**Un aviso para el ensayo:** la pregunta 6 («¿qué significa cautela?») hoy no tiene respuesta en el producto: ningún pick
sale «Con cautela» mientras la revisión de contexto de Intelligence siga en sombra, y la palabra no está en el glosario (la
explica B3). El ensayo se aprueba con 10 de 11, así que las otras diez tienen que salir sin ayuda.

## 3. Lo que nunca cambia

- **PrediGol Intelligence:** ni un pick, una probabilidad, una cuota ni un estado. El recorrido de QA comprueba además que,
  sin picks, el día lo dice con su motivo y nunca muestra un pick inventado.
- **El backend:** el mismo de A14 (ni una línea de `backend/` salvo estas guías).
- **Los datos:** la cuenta del recorrido se crea y se borra en QA; la prueba real se hace con una cuenta tuya de prueba y
  su borrado, si lo quieres, lleva tu confirmación.
- **QA, no producción:** para que el recorrido pueda repetirse muchas veces al día, el messenger de QA escribe sin el tope
  de 90 correos al día (lo prueba su propia prueba del backend); en producción el tope sigue en 90.

## 4. Puertas

Sobre el árbol final de la rama `ux/a16`: **web `258456a4`**; el backend es el de A14 más las guías (solo
`docs/owner`), así que vale su puerta sobre `c6250bfd`. Base de QA `fbi_qa_a16`: copia de `fbi_qa_a15` hecha tras su
copia de seguridad y su prueba de restauración (recuentos idénticos en las 204 tablas; sin migración).

| Puerta | Resultado |
| --- | --- |
| Web: lint | 0 errores (26 avisos, los mismos de antes) |
| Web: tipos | sin errores (la app y las pruebas, con el recorrido nuevo) |
| Web: pruebas unitarias | **896**, las mismas de A15 (A16 no añade lógica) |
| Web: compilación de producción | correcta |
| Backend | sin código nuevo: el de A14 (ruff, mypy y **5.913 pruebas** sobre `c6250bfd`) |
| Gitleaks del rango de la fase | 0 |
| **El recorrido de 16 pasos** (autoservicio y messenger de QA) | **en los dos motores, en verde**: Android 1,2 min, de la invitación a Inicio en **6,7 s**; iPhone (WebKit) 1,5 min, **8,9 s** (el límite es 90 s). En los dos: el día sin picks con su motivo, 6 noticias en el partido, la dependencia del parlay medida («baja»), el mensaje respondido con los dos correos sin las palabras, la sesión cerrada en el servidor y la recuperación que cierra la otra sesión |
| e2e completo, **como arranca producción** (narrativa apagada, transparencia cerrada, tickets encendidos, sin WhatsApp) | 160 / 2 / 19 (40,9 min, 26-oct 20:50–21:31 UTC): los dos, de carga —los mercados de un partido aún cargando a los 20 s y el recorrido de la consola en una tableta táctil pasado de sus 4 minutos—, repetidos solos con un proceso: **2 / 2** |
| Autoservicio con el messenger de QA (cuenta, bienvenida, anónimo, soporte y los dos recorridos) | 34 / 1 / 2 (7,9 min): el fallo, la prueba de las pistas de primera visita pasada de sus 4 minutos con dos procesos (la misma de A15), repetida sola: **1 / 1** |
| Puerta de membresía encendida | 2 / 2 |
| `FBI_SUPPORT=0` | 1 / 1 |
| PWA y axe | sin pantallas nuevas ni cambios en el worker: valen las de A15 (8 / 8 y 0 incumplimientos) |

Los 19 que no corren en el completo son los 17 de A15 (que tienen su propia corrida) y los dos recorridos, que necesitan el
autoservicio y corrieron en la suya.

## 5. Despliegue

A16 no despliega nada propio. El arreglo de Ayuda viaja con el siguiente despliegue de la web después de A15 (o con A15,
si se empaqueta desde la rama de A16, que es A15 más este arreglo y las pruebas). **Vuelta atrás:** la de esa publicación.

## 6. Acción manual

Ninguna ahora. P10 y P11 te los pediré cuando A2…A15 estén desplegadas, encendidas y sin otra tarea tuya abierta, con las
hojas de arriba.
