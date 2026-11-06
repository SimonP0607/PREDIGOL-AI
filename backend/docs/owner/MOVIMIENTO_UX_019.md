# UX-019 · Sistema de movimiento

Plan de cierre de la UX, tarea 5.1. **Solo web: sin migración, sin interruptor, sin IA y sin librerías nuevas** (solo CSS y lo que ya había).

## Qué ve el cliente

- **Tres duraciones:** 120 ms (pulsar), 200 ms (cambio de estado) y 300 ms (cambio de pantalla), con una sola curva. Deportivo, sin parecer un videojuego: las cosas se asientan, no rebotan.
- **Entra en:** el cambio de pestaña (aparece con un fundido), el cambio de pantalla (fundido corto donde el navegador tenga View Transitions), el cambio de estado de un pick (un solo realce), «Seguir» (la estrella se asienta), «Mi parlay» (el botón y la cuenta al añadir una selección), un gol en vivo (el marcador toma el dorado un instante), y los avisos (todos igual, cuatro segundos).
- **Skeletons en lugar de ruedas** en las cargas de datos (Notificaciones, Privacidad, Membresía, Tu fútbol, acceso). La rueda se queda solo en los botones que guardan algo.
- **«Reducir movimiento»** (ajuste del sistema): nada se desliza, late ni se funde. Una rueda de carga sigue girando porque dice «cargando».
- Un marcador que ya estaba ahí **no** parpadea al abrir la pantalla: solo cuando cambia.

## Qué no cambia

Nada del dato: el movimiento solo muestra lo que ya llegó. No cambia un pick, una probabilidad, un estado ni una cuota.

## Cómo se comprueba

Unitarias (duraciones iguales en código y CSS, reducción global, sin librería de animación, el marcador no parpadea al montar) y e2e (con movimiento reducido nada dura más de un parpadeo; CLS < 0,1 en Inicio, Picks y Partidos).
