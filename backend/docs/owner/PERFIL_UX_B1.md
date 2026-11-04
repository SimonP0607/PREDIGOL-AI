# B1 · Perfil: el centro de la cuenta

Plan Maestro UX, fase B1 (sección 21; mantiene en verde G5, G7 y G14). Primera fase del bloque B, el del primer mes. El
perfil deja de ser una página larga de tarjetas sueltas y pasa a ser **un centro de cuenta en 8 bloques**: Cuenta, Fútbol,
Idioma y zona, Notificaciones, Privacidad, Seguridad, Membresía y Ayuda. Coste: 0. Sin migración.

## 1. Qué ve el cliente

- **En el teléfono (y en una tableta, bajo 1024 px):** los 8 bloques plegados, uno debajo de otro, cada uno con su título y
  **una línea que dice cómo está**: «Ana · En prueba hasta el 9 de noviembre», «Sugeridas para Colombia: 8 ligas»,
  «Español · hora de Colombia», «Correos: 6 de 6 temas», «Autorizaciones al día · ninguna solicitud abierta», «Sin
  verificación en dos pasos · 1 sesión abierta», «En prueba hasta el 9 de noviembre.» y «Ningún mensaje abierto». Un toque
  abre el bloque y otro lo pliega. Se llega desde «Más» → Perfil: **dos toques**.
- **En el escritorio (desde 1024 px):** los 8 bloques abiertos, como una página; cada uno se puede plegar.
- **Cuenta:** el **alias** se cambia aquí (1 a 80 caracteres; solo lo ve el cliente, y PrediGol si le escribe), el
  correo, **el estado de la cuenta en palabras** («Activa», «En prueba hasta el …», «Vencida»…; tu cuenta dice
  «Administrador»), desde cuándo existe y cuánto dura una sesión.
- **Fútbol:** las ligas y equipos que sigue, con el mismo selector de la bienvenida (A13).
- **Idioma y zona:** español o inglés y la zona horaria, juntas.
- **Notificaciones:** qué correos recibe por tema (A5). Los avisos en el teléfono llegan con B7.
- **Privacidad:** los consentimientos con su versión y fecha, «Descargar mis datos» y las solicitudes con su plazo (A4).
- **Seguridad:** la contraseña (pide la actual), la verificación en dos pasos, las sesiones con su navegador y último uso,
  y la actividad de acceso; con errores visibles (A1, A7).
- **Membresía:** el estado, el fin, la gracia, los pagos registrados y cómo renovar (A8).
- **Ayuda:** el centro de ayuda, «Reportar un problema», sus mensajes con lo que esperan, el glosario y el WhatsApp cuando
  lo des (P7). Novedades llega con B6.
- **Un enlace lleva a su bloque abierto:** el botón de un correo (`/profile#privacy`), «Elegir mis ligas» de Inicio
  (`#football`), `#membership`, `#notifications` y las direcciones de antes (`#language`, `#timezone`, `#sessions`).

## 2. Lo que nunca cambia

- **PrediGol Intelligence:** nada; el perfil no lee ni un pick ni un modelo.
- **Ningún dato nuevo:** `GET /me/account` resume lo que las fases A4 a A14 ya guardan, de la propia cuenta y de nadie más.
- **Ninguna palabra interna:** ni roles, ni estados en sombra, ni nombres de conjuntos (prueba automática con los 8 bloques
  abiertos).

## 3. Lo nuevo por dentro

- **`GET /api/v1/me/account`** (fuera de las puertas de consentimiento y de membresía, como el perfil): en una sola lectura,
  la línea de cada bloque — alias, correo, fecha de alta; idioma y zona; cuántas ligas y equipos; cuántos temas de correo y
  si el correo rebota; consentimientos pendientes, solicitudes abiertas y su plazo más cercano; verificación en dos pasos,
  sesiones abiertas, último acceso; la membresía; mensajes que esperan o están respondidos y si hay WhatsApp.
- **La web:** un bloque plegable accesible (botón con `aria-expanded`, región con su nombre, foco que se queda en el
  botón), el alias, la ayuda, y el resumen que se vuelve a leer al abrir el perfil y al plegar un bloque tras un cambio. Un
  bloque plegado no carga su contenido.

## 4. Línea base

Medido en QA (la base de A16 antes y la de B1 después), con la cuenta de teléfono de las pruebas, al abrir el perfil:

| Medida | Antes, teléfono 390 px | Después, teléfono | Antes, escritorio 1440 px | Después, escritorio |
| --- | --- | --- | --- | --- |
| Largo de la página | 5.451 px (6,5 pantallas) | **1.175 px (1,4 pantallas)** | 4.421 px (4,9) | 5.084 px (5,6) |
| Lecturas a la API al abrir | 9 | **3** | 9 | 11 |
| Tarjetas con título | 11 sueltas | 8 bloques | 11 | 8 bloques |
| Hasta que termina de cargar | 1,9 s | 1,6 s | 1,8 s | 1,9 s |

En el teléfono el perfil cabe casi en una pantalla y carga solo lo que muestra (la sesión, el resumen y la configuración de
errores); cada bloque lee lo suyo al abrirse. En el escritorio, con todo abierto, la página es algo más larga porque suma
Ayuda y el alias; cada bloque se puede plegar. (Producción hoy: el perfil de A1, con idioma, zona y seguridad; los bloques de
A4 a A14 llegan con sus despliegues.)

## 5. Decisiones que tomé

1. **Plegado bajo 1024 px y abierto en el escritorio.** La sección 21 pide tarjetas plegables en el móvil; en el escritorio
   hay sitio para todo y plegarlo obligaría a un clic por bloque. Los dos se pueden plegar y desplegar.
2. **La línea solo con el bloque plegado.** Abierto, el contenido dice lo mismo con detalle; al plegarlo, la línea se vuelve a
   leer y ya trae lo que el cliente cambió dentro.
3. **Un bloque plegado no carga nada:** el teléfono abre el perfil con 3 lecturas en vez de 9.
4. **`GET /me/account` cuenta con los mismos filtros que cada bloque** (los mensajes «esperando» son los que Ayuda llama así),
   de la propia cuenta y nunca de otra; queda fuera de las puertas de consentimiento y de membresía, como el perfil, para que
   una cuenta limitada vea por qué y cómo renovar.
5. **Las direcciones de antes siguen valiendo:** `#language`, `#timezone`, `#sessions`, `#mfa` y `#password` abren su bloque.
6. **El alias es el único dato que se edita aquí** (1 a 80 caracteres, el mismo campo de siempre). No existe un flujo para
   cambiar el correo; no se inventa en esta fase.
7. **Notificaciones solo con el correo:** las horas silenciosas y los avisos del teléfono llegan con B7 y B8, cuando haya algo
   que silenciar; no se muestran controles que todavía no hacen nada.
8. **Seguridad conserva sus piezas de A1 y A7** (contraseña con la actual, dos pasos, sesiones con navegador y último uso,
   actividad), ahora como partes de un bloque.

## 6. Pruebas

- **Backend:** las cuentas puras de la línea de cada bloque; y contra la base migrada, con sesión real: los 8 bloques de un
  lector nuevo, lo que hace el lector reflejado al momento (un tema de correo apagado, una solicitud de privacidad con su plazo,
  un mensaje que espera y luego respondido, una segunda sesión, el WhatsApp cuando lo das), solo la propia cuenta, 401 sin
  sesión, tu cuenta sin membresía, ninguna palabra interna; y la ruta nueva dentro de la guarda que prueba que ninguna ruta de
  lector sale a internet.
- **Web (unitarias):** la línea de cada bloque en español e inglés y según lo que hizo el lector, el estado de la cuenta en
  palabras, las direcciones que llevan a un bloque, el bloque que se pliega (botón, región, contenido sin montar) y la regla
  del alias.
- **e2e:** `profile.spec.ts` (320 px: los 8 plegados con su línea, a dos toques de «Más», cada uno se abre y se pliega, 44 px,
  nada de lado; teclado; direcciones; escritorio con todo abierto, el alias y ninguna palabra interna; la contraseña actual),
  el paso 10 del recorrido de A16 con los bloques plegados (Android y WebKit) y axe con todo abierto a 390 px.

## 7. Puertas

Sobre el árbol final de la rama `ux/b1`: **backend `37424b74`** y **web `0c82ffc4`**. Base de QA `fbi_qa_b1`: copia de
`fbi_qa_a16` hecha tras su copia de seguridad y su prueba de restauración (204 tablas, 21.251 filas, recuentos idénticos; sin
migración).

| Puerta | Resultado |
| --- | --- |
| Backend: ruff | limpio |
| Backend: mypy estricto | sin errores (502 ficheros; el árbol entero, 1.191) |
| Backend: pruebas | **5.919** en verde (4 se saltan solas), 24,5 min. Una del candado del worker falló por la carga (corría a la vez que el e2e); sola, su fichero entero: **6 / 6** |
| Web: lint | 0 errores (26 avisos, los mismos de antes) |
| Web: tipos | sin errores (la app y las pruebas) |
| Web: pruebas unitarias | **906** (10 nuevas: el centro de cuenta) |
| Web: compilación de producción | correcta |
| Gitleaks del rango de la fase | 0 (los 4 commits de la fase, `b062ce92..ux/b1`) |
| e2e completo **como arranca producción** (narrativa apagada, transparencia cerrada, tickets encendidos, sin WhatsApp) | 163 / 4 / 19 (43,2 min, 26-oct 22:08–22:51 UTC): los cuatro, de carga —Live y la pestaña Avanzado de la consola pasados de su minuto, la cuenta nueva con autenticador y «Más» a 320 px en WebKit (una navegación tardía de la hoja interrumpió la siguiente)—, repetidos solos con un proceso: **4 / 4** |
| Autoservicio con el messenger de QA (cuenta, bienvenida, anónimo, soporte, los dos recorridos y el perfil) | 39 / 1 / 2 (8,9 min): el fallo, las direcciones del perfil (la tercera página seguía en la pantalla de carga a los 15 s, con dos procesos), repetido solo: **1 / 1**. **El recorrido de 16 pasos con los bloques plegados, en verde en los dos motores**: Android 1,7 min, de la invitación a Inicio en 6,8 s; iPhone (WebKit) 3,8 min, 15,5 s (el límite es 90 s) |
| Puerta de membresía encendida | 2 / 2 |
| `FBI_SUPPORT=0` | 1 / 1 |
| axe (WCAG 2.2 A y AA) con la configuración encendida | 29 medidas —las páginas del producto a 1440 y 390 px, «Más», los filtros y **los 8 bloques abiertos a 390 px**—: **0 incumplimientos** |

Los 19 que el completo salta solos son los que tienen corrida propia arriba (5 de cuenta y los 2 recorridos, que necesitan el
autoservicio; la membresía vencida y `FBI_SUPPORT=0`, con su configuración), los 8 de PWA (corrida propia; B1 no cambia el
worker ni el manifiesto) y 2 del glosario que solo corren en escritorio.

## 8. Despliegue

Backend y web juntos (el contrato nuevo cruza los dos), sin migración. Va en la cola de UX después de A15 y del gate.
**Vuelta atrás:** las publicaciones anteriores.

## 9. Acción manual

Ninguna.
