# Inventario de la capa de cliente y de sus datos personales (Plan UX, A0)

*Escrito el 25 de octubre de 2026 sobre el código que corre en producción (backend `6851c0081d75`, web `55366f6bab66`; rama
`plan/f13` en `b0f693e`). Es la línea base de la fase A0 del Plan Maestro UX: lo que hay antes de construir nada, para que
cada fase siguiente se compare contra esto. Solo describe; no cambia ningún modelo, pick, precio ni dato.*

## 1. Pantallas de cliente (web)

Once rutas de `web/src/routes` son de cliente; el resto (31 archivos `admin.*`) es la Consola de administración, solo para
SUPER_ADMIN.

| Ruta | Archivo | Qué es hoy |
| --- | --- | --- |
| `/` | `index.tsx` | Redirige a `/home` con sesión o a `/login` sin ella |
| `/login` | `login.tsx` | Inicio de sesión por etapas (contraseña, segundo factor, contraseña obligatoria) |
| `/home` | `home.tsx` | Inicio: picks del día, los dos parlays, en vivo y mejores cuotas |
| `/matches` | `matches.index.tsx` | Partidos del día en la zona del usuario |
| `/matches/$fixtureId` | `matches.$fixtureId.tsx` | Centro de partido: resumen, estadísticas, mercados, alineaciones y análisis |
| `/live` | `live.tsx` | Partidos en juego |
| `/picks` | `picks.tsx` | Picks registrados del día y lista calificada |
| `/parlays` | `parlays.tsx` | Parlays de PrediGol y armador |
| `/odds` | `odds.tsx` | Mejores cuotas por mercado |
| `/my-picks` | `my-picks.tsx` | Picks y parlays guardados por el usuario y sus resultados |
| `/profile` | `profile.tsx` | Idioma, zona horaria, contraseña, segundo factor y sesiones |

La barra de navegación de cliente tiene siete destinos (Inicio, Partidos, En vivo, Picks, Parlays, Cuotas y Mis picks); el
perfil se abre desde el menú de la cuenta.

## 2. Rutas de la API que usa un cliente

`create_app()` monta tres niveles y nada más: **público** (salud, inicio y cierre de sesión), **app** (cualquier cuenta con
sesión) y **admin** (`/api/v1/admin/*`, solo SUPER_ADMIN; 109 direcciones que un usuario recibe con 403).

- **35 rutas GET** en los niveles público y app (perfil y sesiones, competiciones, partidos y su centro, análisis, pronóstico,
  calendario y conocimiento del partido, cuotas, picks, parlays, mis picks e historial, jugadores, equipos, búsqueda y en vivo).
  Doce aceptan `preview`; las doce responden 403 a un USER (`tests/integration/test_user_layer_guards.py`).
- **18 rutas que escriben**: 12 de la cuenta (`/auth/*`: inicio y cierre de sesión, segundo factor, contraseña, preferencias y
  sesiones) y 6 de lo que guarda el usuario (`/me/picks` y `/me/parlays`: guardar, validar, cambiar la cuota propia y borrar).

Las seis que el plan congela con una instantánea de forma (A0) son `/home`, `/picks`, `/daily`, `/odds/best`, `/me/history` y
`/matches/{id}/center`: `tests/snapshots/client_api_shapes.json`, comprobada por `tests/unit/test_client_api_shapes.py`.

## 3. Datos personales que ya existen y dónde se escriben

| Dónde | Qué guarda | Quién lo escribe | Plazo hoy |
| --- | --- | --- | --- |
| `auth.users` | Email, nombre visible, hash Argon2id de la contraseña, rol, estado, idioma, zona horaria, fechas de alta, último acceso y cambio de contraseña, intentos fallidos y bloqueo, secreto TOTP cifrado y su último paso | `fbi.auth.service` y `fbi.auth.store` (API); `scripts.create_user` y `scripts.accounts` (operador) | Mientras exista la cuenta |
| `auth.sessions` | Hash del token, fechas (creación, caducidad, último uso, revocación y motivo), **user agent (hasta 300 caracteres) e IP**, etapa del inicio de sesión, intentos del segundo factor | `fbi.auth.service._open_session` | Sin purga |
| `auth.audit_events` | Acción, autor, cuenta afectada, **email** (en un inicio fallido, la dirección tal como se tecleó), **IP** y detalle (incluye el user agent en los inicios de sesión) | `fbi.auth.store.record_event` y la auditoría de escrituras de admin de `fbi.api.app` | Sin purga |
| `auth.recovery_codes` | HMAC de los códigos de recuperación y cuándo se usaron | `fbi.auth` | Mientras exista la cuenta |
| `picks.user_picks`, `picks.user_parlays`, `picks.user_parlay_legs` | Lo que el usuario guarda (partido, mercado, cuota, su cuota propia) y cómo terminó | API (`fbi.api.services.records`); el worker los liquida | Mientras exista la cuenta |
| Registro de la API (contenedor `predigol-api`, JSON) | Método, ruta, estado, milisegundos y `request_id` por petición; `user_id`, rol y etapa en cada inicio de sesión. **Ni email, ni IP, ni token, ni cuerpo** | `fbi.api.app` y `fbi.auth.service` | Rotación por tamaño (20 MB × 5) |
| Registro de Caddy | **IP, user agent y URI** de cada petición; las cookies, redactadas | Caddy | 30 días (por tamaño) |

No hay datos de pago, ni documentos de identidad, ni ubicación, ni analítica de terceros. Ningún proceso de PrediGol
Intelligence lee estos datos: el rol del worker no tiene `USAGE` sobre el esquema `auth`
(`tests/integration/test_db_roles.py::test_the_worker_sees_nothing_of_the_accounts`) y ningún paquete fuera de `fbi.api` importa
`fbi.auth` ni `fbi.userdata` (`tests/unit/test_user_layer_isolation.py`). El analista de la consola (`fbi.analyst`) no puede
cargar ningún módulo que los toque ni ningún archivo que nombre una tabla de `auth`, de `customer` o los picks de un usuario.

**Lo que el plan cambia de esto** (no se toca en A0): el esquema `customer` y su inventario (A4), el registro de quién
consintió qué (A4), la sesión deslizante (A1), el borrado y la exportación de la cuenta (A4) y la tabla de plazos (A4, con el
plan de seguridad). El email tecleado en un inicio fallido, guardado tal cual en `auth.audit_events`, es el hallazgo R18 del plan
de seguridad.

## 4. Las guardas que A0 deja en marcha

| Prueba | Qué vigila | Archivo |
| --- | --- | --- |
| Instantáneas de forma | Que la capa de usuario no cambie lo que ya responden las seis rutas de cliente | `tests/unit/test_client_api_shapes.py` y `scripts/api_shapes.py` |
| Importaciones prohibidas | Solo la API importa la capa de usuario; el analista no alcanza datos de clientes; ninguna ruta de cliente importa un cliente de IA, la búsqueda ni HTTP | `tests/unit/test_user_layer_isolation.py` |
| Ninguna visita sale a la red | Las 35 rutas GET de cliente llamadas con la red cerrada: ni IA, ni Exa, ni el proveedor | `tests/integration/test_user_layer_guards.py` |
| Vista en sombra | Las doce rutas con `preview` responden 403 a un USER y lo que lee un USER es lo calificado | `tests/integration/test_user_layer_guards.py` (refuerza `test_auth_rbac.py`) |
| Marca `integration` | `pytest -m "not integration"` es solo la suite unitaria | `tests/integration/conftest.py` y `tests/unit/test_integration_marker.py` |
| Huella del código de modelos | `mc9a7bec97ca`, sin cambio | `tests/unit/test_model_code_version.py` y `scripts/model_code_guard.py` (ya existían) |

Cada guarda nueva se probó rompiéndola a propósito, seis veces: una llamada HTTP metida en `/home`, la ruta del pronóstico
dejando pasar la vista previa a un USER, una importación de `fbi.auth` en `fbi.picks`, un SQL de `auth.users` en las herramientas
del analista, `httpx` importado en el router de producto y la búsqueda de Exa importada en el servicio de registros; las seis
roturas se detectaron y el código volvió a su estado.
