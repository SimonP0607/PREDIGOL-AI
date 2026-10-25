# Secretos: qué se vigila, cómo y qué hacer si algo sale (R07)

Plan de seguridad PrediGol, fase S1 (R07). **Los secretos se nombran y nunca se muestran**: ni en un chat, ni en un issue, ni en un prompt, ni en este repositorio.
Aquí viven la configuración de Gitleaks, el hook de pre-commit, el paso de la CI y la puerta de cada lanzamiento. Nada de esto está en `backend/` ni en `web/`:
no viaja en ningún paquete de lanzamiento y no cambia lo que corre en producción.

## Qué hay

| Pieza | Para qué |
| --- | --- |
| `.gitleaks.toml` | Reglas de fábrica de Gitleaks + **reglas propias** que no miran la entropía (una clave real de 32 hexadecimales puede quedar por debajo de la que exige la regla genérica): las variables secretas de PrediGol **por su nombre** (`FBI_APIFOOTBALL_KEY`, `POSTGRES_PASSWORD`, `FBI_AUTH_SECRET_KEY`, ...), la cabecera `x-apisports-key`, la contraseña dentro de una URL de base de datos, la URL de ping de Healthchecks.io y las claves de Resend y de Supabase por su formato. Excepciones, todas con su motivo: las constantes **fijas y falsas** de las pruebas (carpeta `tests/`, líneas que asignan `TEST_AUTH_KEY`, `SECRET` o un `"password":`; URLs de `localhost` en `tests/`), tres etiquetas de código clasificadas (`BET_PRICE_KEY`, `baseline_key`, `key=cfg.cookie_name`, solo en sus ficheros y con esa forma), la plantilla `deploy/env_example.txt` (solo para la regla genérica) y los valores de relleno de las plantillas (`change-me`, `<...>`, `${VAR}`, vacío) |
| `.gitleaksignore` | Las coincidencias del historial ya clasificadas, una a una, cada una con su motivo (hoy 6, todas código o claves de prueba; las que no se pueden describir por su contenido) |
| `.githooks/pre-commit` | Escanea lo que se va a confirmar. Un hallazgo bloquea el commit |
| `security/scan.sh` | El único sitio donde se decide cómo se corre Gitleaks: `staged` (hook), `history` (todo el historial) y `range <base> <head>` (la puerta de un lanzamiento) |
| `security/selftest.sh` | **La prueba de que la red funciona**: en un repositorio de juguete, con secretos falsos fabricados al momento, comprueba que se bloquean (y por la regla esperada), que las plantillas y las constantes de las pruebas pasan, y que `scan.sh` ve lo que el hook no vio. Una treintena de comprobaciones; se corre al instalar, al tocar `.gitleaks.toml` y en la CI |
| `security/install-git-hooks.sh` | Activa los hooks de este clon (`core.hooksPath`) y corre el historial y la autoprueba |
| `security/GITLEAKS_VERSION` | Versión fijada y huellas SHA-256 de la publicación oficial |
| `.github/workflows/gitleaks.yml` | La CI: historial completo en cada push a `main` y en cada pull request (se activa cuando el repositorio esté en GitHub con Actions) |

Salida de `security/scan.sh`: **0** limpio · **1** hallazgos · **2** el escáner no pudo mirar (nunca se toma como luz verde).

## Instalar (una vez por clon)

1. Gitleaks **8.30.1**, el binario oficial: <https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1>. Comprueba su SHA-256 con `security/GITLEAKS_VERSION`.
   - Windows: `gitleaks_8.30.1_windows_x64.zip`; deja `gitleaks.exe` donde quieras y apunta `GITLEAKS_BIN` a él (o ponlo en el `PATH`).
   - Linux: `gitleaks_8.30.1_linux_x64.tar.gz`.
2. `security/install-git-hooks.sh` (en Windows, desde Git Bash). Corre el historial entero y la autoprueba una vez para comprobar que todo funciona.
3. Si el clon aún no trae estos ficheros (la rama con la guarda no está en él), usa una copia de la carpeta de la guarda: `git config core.hooksPath <carpeta de la guarda>/.githooks`;
   el hook y `scan.sh` leen la configuración de esa carpeta (`PREDIGOL_GUARD_DIR`).

Omitir el hook a propósito: `SKIP_GITLEAKS=1 git commit ...` (o `--no-verify`). Se vuelve a mirar en la puerta de lanzamiento y en la CI. Si el escáner no puede correr, el hook
**avisa y deja pasar**; `GITLEAKS_REQUIRED=1` lo hace bloquear también en ese caso.

## En cada lanzamiento

`security/scan.sh range <commit desplegado> <commit nuevo>` debe dar 0 y se anota en la hoja de puertas del lanzamiento. Cada ciclo de seguridad
(S6 y S15) corre además `security/scan.sh history` sobre el monorepo y, para los demás repositorios del dueño, el mismo escaneo sobre un espejo.

## Si Gitleaks marca algo

1. **No pegues el valor en ningún sitio.** Anota `SECRET_EXPOSED` con el **tipo** y el **lugar** (fichero, línea, commit).
2. **Si es real y ya salió del portátil** (push, paquete, chat): **revócalo primero** en el panel del proveedor y rota después. Reescribir el historial no lo arregla, porque la copia
   ya pudo hacerse, y la regla del proyecto prohíbe reescribir historia publicada. Si solo está en un commit local sin publicar, se quita y se vuelve a confirmar.
3. **Comprueba si es el de producción** comparando huellas SHA-256 truncadas, sin imprimir ningún valor (plan S1.d). Si lo es, la rotación de producción es parte de la revocación.
4. **Si es una constante falsa de una prueba o un relleno de plantilla:** declárala como lo hacen las demás (`SECRET = "..."` o `"password": "..."` dentro de `tests/`; en una plantilla,
   un marcador claro como `<generar>` o `change-me`) o, si es una sola línea, añade `# gitleaks:allow` al final de esa línea con el motivo al lado.
   Nunca una expresión amplia en `.gitleaks.toml`; y si cambias una regla, corre `security/selftest.sh` y `security/scan.sh history`: los dos deben quedar en verde.
5. **Si es código que se parece a un secreto** (el nombre de una etiqueta, un argumento de cookie): una línea en `.gitleaksignore` con la huella (`commit:fichero:regla:línea`,
   que imprime Gitleaks) y **su explicación** encima.

## Lo que Gitleaks no ve

Reglas de fábrica y reglas propias por nombre y formato: un secreto con otro nombre y sin formato reconocible (por ejemplo una contraseña nueva en una variable que no está en la lista), una contraseña de menos de 12 caracteres en una variable
secreta, o un valor dentro de un fichero binario o cifrado, puede pasar. Cuando aparezca un secreto nuevo en el proyecto, su nombre se añade a la regla `predigol-secret-by-name`. Tampoco mira
issues, pull requests, wikis ni chats. Por eso la defensa no es solo el escáner: los secretos viven en ficheros de entorno 600 que nunca entran en Git (`.env` está en `.gitignore`),
los agentes de IA no leen ficheros de entorno y todo lo que se haya publicado alguna vez se revoca (plan de seguridad, sección 17).
