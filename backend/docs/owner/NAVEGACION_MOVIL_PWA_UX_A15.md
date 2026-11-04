# A15 · Navegación móvil y PWA base

Plan Maestro UX, fase A15 (gate **G11 · Móvil**). **Solo web**: sin backend, sin migración y sin servicios externos. Coste: 0.
PrediGol pasa de siete destinos con etiquetas de 10–11 px a **cinco destinos** —Inicio, Partidos, Picks, Mis picks y
«Más»— en el teléfono y en el escritorio, con todo lo demás a dos toques. Ninguna dirección cambia.

## 1. Qué ve el cliente

- **La barra de abajo (teléfono y tableta, hasta 1023 px):** cinco celdas —Inicio, Partidos, Picks, Mis picks y Más—, con
  etiquetas de **12 px**, enteras a 320 px (64 px por celda; antes, siete celdas de 46 px con etiquetas de 10 px). La celda
  de la página en la que está queda marcada (dorada y anunciada a un lector de pantalla). De lado, icono y etiqueta en una
  fila, como antes.
- **«Más»:** una hoja que sube desde abajo, al alcance del pulgar, con **Parlays, Cuotas, Transparencia, Ayuda, Perfil y
  Glosario**, en el orden del plan, cada una con una línea que dice qué hay dentro; después **«Instalar PrediGol»** y
  **«Cerrar sesión»** (que revoca la sesión en el servidor, igual que el menú de la cuenta). Transparencia solo aparece
  cuando tú abres «Cómo le va a PrediGol» a los lectores (A12). Las páginas de «Más» encienden su celda. **Perfil, Ayuda y
  Transparencia quedan a dos toques de cualquier pantalla**; el menú de la cuenta (arriba) sigue como estaba.
- **«Instalar PrediGol»:** los pasos básicos, primero los de su dispositivo: en iPhone o iPad, Safari → Compartir →
  «Agregar a Inicio» (y «Abrir como app web» si aparece); en Android, Chrome → Más (⋮) → «Instalar y crear acceso directo»
  (o «Agregar a la pantalla principal»); en un computador, el icono de instalar de Chrome o Edge. Dentro de la app ya
  instalada no se ofrece. (Textos de los pasos según las ayudas oficiales de Apple y de Google, en español de
  Latinoamérica.)
- **En vivo es un filtro de Partidos:** el chip «En vivo» de Partidos filtra el día a un toque, sin desplazarse. Mientras hay
  partidos en juego, con ese filtro aparece **«Abrir el tablero en vivo»** (cada partido con sus estadísticas y los picks de
  PrediGol primero, cada 15 segundos). El tablero sigue en su dirección (`/live`), ahora con **«Volver a Partidos»** arriba, y
  la celda de Partidos se enciende en él. Inicio sigue llevando a él con «Ver todos».
- **Filtros en una hoja desde abajo** (por debajo de 1024 px): en **Partidos, En vivo, Picks** (los dos bloques) y
  **Cuotas**, un botón **«Filtros»** dice cuántos hay puestos; la hoja trae los filtros con su nombre escrito, **«Ver N
  partidos»** (o selecciones, o picks) al alcance del pulgar y **«Borrar filtros»**. La lista de detrás cambia al momento.
  En la página se quedan el día, el estado (Todos · En vivo · Próximos · Finalizados), la ventana y el mercado. Desde
  1024 px los filtros siguen en la fila de la página, como hoy.
- **Escritorio (desde 1024 px):** la barra de arriba con **los mismos grupos**: Inicio, Partidos, Picks, Mis picks y un menú
  **«Más»** con las mismas entradas (Parlays y Cuotas quedan ahí también en el escritorio).
- **Letra:** ningún texto para leer queda por debajo de **12 px** en un teléfono o una tableta (contadores, etiquetas,
  insignias, notas de las cuotas, de los partidos y del perfil); en el escritorio sigue en 11 px. No cuentan como texto
  para leer las iniciales que sustituyen un escudo que no carga, la cancha de las alineaciones (un dibujo con su
  descripción) ni el lema del logo.
- **Alcance del dedo:** los términos relacionados del glosario y el índice de los textos legales llegan a 44 × 44 px (eran
  24 y 40 px).

## 2. Lo que nunca cambia

- **PrediGol Intelligence:** ni un pick, una probabilidad, una cuota, un estado ni un umbral; la web solo reorganiza cómo se
  llega a ellos. **Backend: el mismo árbol que A14** (ni una línea de `backend/` salvo esta guía).
- **Ninguna dirección cambia:** `/live`, `/parlays`, `/odds`, `/profile`, `/help`, `/help/glossary`, `/transparency`… siguen
  donde estaban; un enlace guardado sigue valiendo.
- **La PWA:** el manifiesto, el service worker (versión `predigol-v3`, sin cambios) y la página sin conexión son los mismos;
  la API nunca se sirve desde caché y una página nunca se muestra vieja como actual.
- **Seguridad y privacidad:** sin datos nuevos. El único dato nuevo de la web es una marca local del dispositivo
  (`predigol.pwa_installed`, una fecha) para enviar una sola vez el evento `pwa_installed`, que solo se guarda si tú
  enciendes la medición (A6).

## 3. La PWA (sección 35 del plan)

| Pieza | Qué hay | Cómo se comprueba |
| --- | --- | --- |
| Instalación | Pasos básicos en «Más» | Chrome no encuentra ningún impedimento para instalarla (`Page.getInstallabilityErrors` vacío, compilación de producción); en iPhone, las metas de app ya estaban. **Falta tu prueba en un iPhone y un Android reales** (sección 9) |
| Actualización | Controlada: la versión nueva espera a que el lector diga «Actualizar ahora» | e2e nuevo: una versión nueva del worker se instala y **espera**, «Más tarde» no cambia ni el código ni las cachés, «Actualizar ahora» cambia **una vez** (una recarga) y retira las cachés de la versión anterior; y una prueba unitaria de que un trozo de código que ya no existe tras un despliegue recarga la página una sola vez |
| Áreas seguras | La barra, «Más» y los filtros respetan la muesca y la barra de gestos | e2e: la hoja sube desde el borde de abajo; en un dispositivo real, en tu prueba |
| Sin conexión | La página propia de PrediGol | e2e (ya estaba) y la versión nueva vuelve a guardarla al instalarse |
| Permisos | Nunca se piden al abrir | e2e: ni avisos, ni push, ni ubicación, con y sin sesión (los avisos llegan con B7, en contexto) |

**Evento `pwa_installed`:** la primera vez que la app instalada se abre en un dispositivo (la regla que también cuenta un
iPhone, que no avisa de la instalación). No se usa además el aviso de instalación de Chrome para no contar dos veces. Un
dispositivo que ya la tenía instalada antes de A15 cuenta en su primera apertura después del despliegue.

## 4. Línea base

Sin tocar producción: lo que corre se lee del commit desplegado (web `3c4c9b1a4e0f`, A1) y lo demás se midió en QA.

- **Producción hoy:** siete destinos (Inicio, Partidos, En vivo, Picks, Parlays, Cuotas, Mis picks), etiquetas de 10 px
  (11 px desde 360 px), celdas de 46 px a 320 px; Perfil, Ayuda y Glosario solo en el menú de la cuenta, arriba a la
  derecha; ningún «Instalar»; worker `predigol-v3`.
- **Letra bajo 12 px** (QA, teléfono de 390 px, 14 páginas del producto): **139 textos antes, 0 después**; 0 también a
  320 px y en las siete secciones de seis partidos (42 vistas).
- **Tamaño del código** (compilación final): JS 3.501.707 → 3.521.972 bytes (+0,58 %; comprimido +0,64 %), CSS +0,54 %
  (comprimido +0,34 %). La regla del plan es no crecer más de un 10 % por fase.
- **LCP** (lo que tarda en dibujarse lo principal de la página; compilación de producción con compresión como la de
  Caddy, teléfono de 390 px con sesión, 4G lento simulado —150 ms, 1,6 Mbps— y CPU 4 veces más lenta; mediana de 3;
  las dos versiones medidas a la vez sobre la misma máquina el 26-oct entre las 19:36 y las 19:43 UTC; A14 = todo lo
  anterior a A15):

| Página | Primera visita A14 | Primera visita A15 | Visita repetida A14 | Visita repetida A15 |
| --- | --- | --- | --- | --- |
| Inicio | 5,4 s | 5,5 s | 2,8 s | 2,7 s |
| Partidos | 1,1 s | 1,1 s | 0,4 s | 0,4 s |
| Picks | 5,1 s | 4,9 s | 2,5 s | 2,3 s |
| Mis picks | 4,7 s | 4,9 s | 2,5 s | 2,4 s |
| Cuotas | 4,7 s | 5,0 s | 2,4 s | 2,3 s |

  A15 no cambia el LCP de forma que se pueda medir: en la primera visita entre −0,2 y +0,4 s según la página (la
  medición misma varía así de una vuelta a otra) y en la repetida igual o algo mejor; añade 5–7 KB de código por página.
  Una medición anterior, a mitad de la fase y antes de que «Más» se cargara solo al abrirse, dio lo mismo (+0,0 a +0,4 s).

  **Hallazgo (no lo causa A15):** en la primera visita con 4G lento la página tarda unos 5 s en dibujarse —la app descarga
  ≈ 500 KB de código comprimido y pregunta por la sesión antes de pintar—, así que **no cumple los 2,5 s del plan**;
  en la visita repetida o con la app instalada (el código sale de la caché) queda en 2,3–2,8 s. Lo dejo anotado para el
  gate A16 con una propuesta en la sección 10.

## 5. Decisiones que tomé

1. **En vivo:** filtro de Partidos (el chip que ya existía) y el tablero a un toque más mientras hay partidos en juego, en su
   misma dirección, con «Volver a Partidos». Fusionar el tablero dentro de la lista de Partidos habría mezclado dos
   conjuntos de filtros y perdido el orden «picks de PrediGol primero»; así no se pierde nada y la barra queda en cinco.
2. **Escritorio con los mismos grupos (sección 37):** «Más» es un menú arriba; Parlays y Cuotas quedan a dos clics también
   en el escritorio. Una sola forma de moverse en todos los tamaños.
3. **Los filtros aplican al momento** y «Ver N» cierra la hoja: el lector ve el efecto sin un paso de «Aplicar».
4. **12 px con dos utilidades** (`text-label` y la nueva `text-micro`: 11 px en escritorio, 12 px bajo un dedo) en vez de
   página por página: cubre todas las pantallas del recorrido, también las de A4 a A14, y las futuras.
5. **«Instalar PrediGol» solo con instrucciones:** el botón de instalación de Android (`beforeinstallprompt`) y la guía en
   contexto son de B7; A15 no toca el aviso propio de Chrome.
6. **El worker no cambia de versión:** los archivos llevan huella y la página se pide siempre a la red, así que no hace
   falta; cambiarla habría hecho aparecer «Hay una versión nueva» sin nada nuevo en el worker.
7. **La prueba de actualización necesita que el servidor sirva una versión nueva** (el navegador pide el worker por su
   cuenta, fuera del alcance de la prueba): en QA lo hace la puerta de entrada de QA; contra un sitio desplegado esa prueba
   se salta y queda en tu prueba manual.
8. **El foco vuelve a «Más» o a «Filtros» al cerrar su hoja** (teclado y lector de pantalla); si se cerró eligiendo una
   página, el foco queda en la página nueva.
9. **«Más» se monta la primera vez que se abre**, para que ninguna carga de página pague una hoja que nadie pidió.
10. **Dos correcciones de pruebas que A15 destapó:** el recorrido de anchos abre una pestaña por página (doce páginas en una
    pestaña agotaban la memoria del navegador de pruebas) y una petición que WebKit cancela al dejar una página ya no cuenta
    como fallo (Chromium ya se ignoraba así).

## 6. Pruebas

- **Unitarias (web, 896; +23):** las dos barras (cinco celdas de 12 px, la celda de la página, En vivo dentro de
  Partidos, la de «Más» con su estado), «Más» (orden, filas de 56 px, Transparencia solo abierta, sin instalar dentro de la
  app), los pasos de instalación por dispositivo, el botón «Filtros» (número, palabras para el lector de pantalla, la hoja
  no está hasta que se abre), el número de filtros de Picks, las ayudas de instalación (`isStandalone`,
  `installPlatform`, `installOrder`, la marca de una vez por dispositivo y sin almacenamiento nunca), la limpieza de cachés
  de una versión vieja y la recarga única tras un despliegue.
- **e2e:** ver la sección 7; `responsive.spec.ts` (las pruebas nuevas llevan «320 px phone» en el nombre, así que corren
  también en WebKit), `user.spec.ts`, `pwa.spec.ts` (compilación de producción) y `a11y.spec.ts`.

## 7. Puertas

Sobre el árbol final de la rama `ux/a15`: **web `bdbb1d65`**; el backend es el de A14 más esta guía (solo
`docs/owner`), así que vale su puerta sobre `c6250bfd`. Base de QA `fbi_qa_a15`: copia de `fbi_qa_a14` hecha tras su
copia de seguridad y su prueba de restauración (sin migración en esta fase).

| Puerta | Resultado |
| --- | --- |
| Web: lint | 0 errores (26 avisos, los mismos que en A14) |
| Web: tipos | sin errores (la app y las pruebas e2e) |
| Web: pruebas unitarias | **896** (A14: 873) |
| Web: compilación de producción | correcta |
| Backend | sin código nuevo: ruff, mypy (500 y 1.187 ficheros) y **5.913 pruebas** sobre `c6250bfd`, la puerta de A14 |
| Gitleaks del rango de la fase | 0 |
| e2e completo, **como arranca producción** (narrativa apagada, transparencia cerrada, tickets encendidos, sin WhatsApp) | **162 / 0 / 17** (39,5 min, 26-oct 18:51–19:30 UTC, sobre el árbol final) |
| e2e completo, encendido (narrativa, transparencia abierta, tickets, WhatsApp de QA) | 158 / 4 / 17 (37,3 min, sobre el árbol anterior): los cuatro, en el recorrido de tabletas (tres «page crashed» por memoria de la máquina de pruebas y un esqueleto bajo carga); arreglado abriendo una pestaña por página (`63ebfaf6`) y las seis medidas de tableta repetidas sobre el árbol final: 6 / 6 |
| Autoservicio con el messenger de QA (cuenta, bienvenida, anónimo y soporte) | 31 / 2 / 2 (5,4 min): los dos, de carga —una página que a los 15 s aún cargaba su código y un esqueleto ocupado a los 20 s—, repetidos solos con un proceso: 2 / 2 |
| Puerta de membresía encendida | 2 / 2 (una cuenta limitada en un teléfono de 320 px, con la barra nueva y «Más») |
| `FBI_SUPPORT=0` | 1 / 1 |
| PWA (compilación de producción tras la puerta de entrada de QA, con compresión) | **8 / 8**: manifiesto e iconos, el worker controla el sitio, nunca responde por la API, página sin conexión, ningún impedimento para instalar, ningún permiso al abrir (con y sin sesión), actualización controlada |
| axe (WCAG 2.2 A y AA) | **0 incumplimientos** en 28 vistas: la entrada y 12 páginas del producto a 1440 y a 390 px (entre ellas Ayuda, el glosario, transparencia y los textos legales) y, a 390 px, «Más» y la hoja de filtros de Partidos abiertas |
| WebKit (Safari) a 320, 390 y 430 px | dentro del completo: 10 / 10 |

Los 17 que no corren en el completo son los que tienen su propia corrida (8 de la PWA, 5 del autoservicio, 1 de
`FBI_SUPPORT=0` y 1 de la puerta de membresía) y 2 del glosario que solo corren en el escritorio.

## 8. Despliegue

Solo web, sin migración y sin reinicio de la API ni del worker. Va en la cola de UX después de A2…A14 (una por ventana, con
copia previa por regla aunque no haya migración). **Vuelta atrás:** la publicación web anterior.

## 9. Acción manual (tuya, después de desplegar A15)

El gate G11 pide **la PWA instalada en un iPhone y en un Android reales**. Unos 10 minutos por teléfono; te lo pediré cuando
A15 esté en producción y no tengas otra tarea abierta:

1. Abrir PrediGol en Safari (iPhone, iOS 16.4 o posterior) o en Chrome (Android) e iniciar sesión.
2. Abrir «Más» → «Instalar PrediGol» y seguir los pasos de tu teléfono.
3. Abrir PrediGol desde el icono: pantalla completa, sin barra del navegador.
4. Mirar que la barra de abajo no queda debajo de la barra de gestos del sistema y que arriba nada queda bajo la muesca.
5. Abrir «Más» y los filtros de Partidos: suben desde abajo y se cierran con la X o tocando fuera de la hoja.
6. Modo avión → abrir otra página: debe salir «Sin conexión», nunca datos viejos. Quitar el modo avión y reintentar.
7. Tras el siguiente despliegue: al volver a la app debe aparecer «Hay una versión nueva» y, al aceptarla, recargar una vez.
8. Decirme qué viste (o mandarme capturas sin datos personales).

## 10. Pendiente y propuestas

- **LCP de la primera visita (≈ 5 s en 4G lento):** propongo para antes del gate A16 (sin coste): separar el código de la
  consola del del lector, pedir la sesión y los datos de la página en paralelo y precargar la fuente; meta 2,5 s. Es un
  cambio de arquitectura de la web: lo dejo como propuesta, no lo hago dentro de A15.
- **Lo que espera a otras fases:** Novedades en «Más» (B6), la instalación guiada con el botón de Android y los avisos push
  (B7), el diseño propio de tableta (C5) y el uso sin conexión completo (C8).
