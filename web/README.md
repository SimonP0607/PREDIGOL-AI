# Football Intelligence Hub

ROL EXPERTO

Actúa como Lead Product Designer + Senior Frontend Architect + UX Engineer especializado en plataformas deportivas intensivas en datos.

Quiero que uses Lovable para construir la primera versión visual y funcional del frontend de una plataforma privada llamada provisionalmente:

Football Intelligence Platform

No es una web genérica de apuestas, no es un casino y no es una landing page. Es una herramienta privada de inteligencia futbolística, análisis cuantitativo, probabilidades, cuotas, modelos y seguimiento de picks.

Tu objetivo es construir una interfaz que pueda evolucionar posteriormente hacia producción conectándose a nuestro backend real.

OBJETIVO

Construye una aplicación web premium, profesional y data-driven para analizar fútbol y detectar oportunidades cuantitativas en mercados deportivos.

La plataforma futura recibirá datos principalmente de:

API-Football / API-SPORTS
        ↓
Backend FastAPI propio
        ↓
PostgreSQL
        ↓
Modelos estadísticos
        ↓
Odds Engine
        ↓
Prediction Engine
        ↓
Value Engine
        ↓
Pick Engine
        ↓
Frontend

La aplicación que construyas ahora debe centrarse principalmente en:

PRODUCT UX
+
INFORMATION ARCHITECTURE
+
DESIGN SYSTEM
+
FRONTEND FOUNDATION
+
REALISTIC DEMO DATA

No quiero que Lovable invente todavía el motor estadístico ni replique lógica de backend.

CONTEXTO DEL PROYECTO

Estamos reconstruyendo desde cero un sistema antiguo de análisis de fútbol.

El sistema legacy tenía aproximadamente:

61.000 partidos históricos;

modelos Poisson y Elo;

API-Football;

histórico de competiciones;

bot Telegram;

análisis de cuotas;

picks;

backtesting.

Sin embargo descubrimos errores científicos importantes y estamos reconstruyendo completamente el motor de decisión.

La V2 seguirá estos principios:

DATA
 ↓
FEATURES
 ↓
MODEL
 ↓
PROBABILITY
 ↓
MARKET
 ↓
VALUE
 ↓
DECISION
 ↓
PICK
 ↓
RESULT
 ↓
LEARNING

Cada predicción deberá ser:

REPRODUCIBLE
TRACEABLE
VERSIONED
TESTABLE
AUDITABLE
EXPLAINABLE

ARQUITECTURA REAL DEL BACKEND

La infraestructura real se está construyendo localmente con:

Python
FastAPI
PostgreSQL 16
SQLAlchemy 2
Alembic
Polars
NumPy
SciPy
scikit-learn
Docker Compose

El frontend NO debe depender de Supabase.

MUY IMPORTANTE

No utilices Supabase como backend automático aunque Lovable lo sugiera.

No construyas autenticación, DB o lógica crítica alrededor de Supabase.

Diseña una capa frontend desacoplada:

Frontend
   ↓
API Client
   ↓
NEXT_PUBLIC_API_BASE_URL
   ↓
FastAPI

Durante esta etapa utiliza datos DEMO/mock.

PRINCIPIO DE DATOS DEMO

Todos los datos que todavía no provengan del backend real deben considerarse:

DEMO DATA

No presentes:

ROI ficticio;

rentabilidad falsa;

picks ganadores inventados;

probabilidades como resultados reales;

performance falsa;

como si fueran métricas reales de nuestro sistema.

Cuando corresponda utiliza estados como:

No disponible todavía
Muestra insuficiente
Pendiente de validación
Shadow Mode
Demo Data

Quiero que el producto transmita confianza precisamente porque no inventa resultados.

DIRECCIÓN VISUAL

Diseña una identidad propia de:

SPORTS INTELLIGENCE
+
QUANTITATIVE ANALYTICS
+
INSTITUTIONAL TRADING TOOL

La referencia conceptual es un dashboard oscuro de deportes con acento verde, pero NO quiero copiar ninguna interfaz existente.

Estética

Quiero:

dark premium;

sofisticada;

moderna;

precisa;

técnica;

rápida;

limpia;

información densa pero muy organizada;

tablas excelentes;

gráficos profesionales;

excelente jerarquía visual.

Evitar:

estética casino;

diseño de bookmaker tradicional;

estilo gamer;

exceso de neón;

fondos llenos de gradientes;

animaciones innecesarias;

tarjetas gigantes para cada pequeño dato;

interfaces tipo plantilla genérica SaaS.

PALETA

Utiliza una base oscura sofisticada.

Conceptualmente:

Background Base      casi negro verdoso
Surface              charcoal / green-black
Elevated Surface     ligeramente más clara
Border               gris verdoso discreto

Text Primary         casi blanco
Text Secondary       gris frío
Text Muted           gris oscuro

Accent Primary       verde eléctrico sofisticado

Positive             verde
Negative             rojo
Warning              ámbar
Info                  azul

El verde de marca debe utilizarse con moderación.

No conviertas toda la interfaz en verde.

TIPOGRAFÍA

Prioriza legibilidad numérica.

Necesitamos distinguir:

Display
Heading
Title
Body
Label
Caption
Numeric
Tabular Numeric

Los números importantes deben tener:

font-variant-numeric: tabular-nums;

cuando corresponda.

APP SHELL

Crea una estructura desktop profesional con:

Sidebar izquierda

Logo/proyecto arriba.

Navegación principal.

Topbar

Debe poder incluir:

búsqueda global;

estado del sistema;

última sincronización;

command/search;

usuario;

configuración.

Main Content

Ancho amplio y optimizado para tablas/gráficas.

NAVEGACIÓN GENERAL

Diseña la arquitectura para soportar:

Overview
Matches
Picks
Odds
Performance

Intelligence
 ├─ Models
 ├─ Backtesting
 └─ Analytics

Football
 ├─ Competitions
 ├─ Teams
 └─ Rankings

System
 ├─ AI Analyst
 ├─ Data Quality
 └─ Settings

No es necesario completar todo en profundidad en la primera generación.

PRIMERA ITERACIÓN QUE QUIERO QUE CONSTRUYAS

Construye completamente el:

APP SHELL
+
DESIGN SYSTEM
+
NAVIGATION
+
ROUTING

y lleva a alta fidelidad estas cuatro vistas:

1. Overview
2. Match Center
3. Picks Center
4. Models

Además crea rutas estructuradas con estados placeholder profesionales para:

Matches
Odds
Performance
Backtesting
Analytics
Competitions
Teams
Rankings
AI Analyst
Data Quality
Settings

No quiero páginas vacías con simplemente un título.

Cada placeholder debe explicar qué módulo contendrá.

1 — OVERVIEW

La home será un centro de operaciones, no una landing page.

Debe responder inmediatamente:

¿Qué está ocurriendo hoy en el sistema?

Organízala aproximadamente en:

Top Context

Today
fecha
fixtures monitorizados
última sincronización
estado sistema

Upcoming Matches

Tabla o lista compacta:

Hora
Liga
Local
Visitante
Market Coverage
Model Status
Odds Status

Opportunities

Tabla de candidatos:

Fixture
Market
Selection
Model Probability
Market Probability
Fair Odds
Best Odds
Edge
EV
Status

Por ahora usar DEMO DATA.

System Health

API-Football
Database
Worker
Last Capture
Requests Today
Data Freshness

Model Health

Market Baseline
Poisson
Elo
Dixon-Coles

con estados como:

Research
Shadow
Validated
Insufficient Data

Performance

En lugar de inventar rentabilidad:

P&L             —
ROI             —
CLV             —
Published Picks 0

Muestra insuficiente para concluir

2 — MATCHES

Diseña una tabla profesional.

Columnas potenciales:

Time
Competition
Fixture
Status
Model
Odds
Markets
Data Quality
Actions

Filtros:

Date
Competition
Status
Model Availability
Odds Available

Soporta:

Upcoming
Live
Finished

aunque live todavía no esté implementado realmente.

3 — MATCH CENTER

Esta será una de las pantallas más importantes de toda la plataforma.

URL conceptual:

/matches/:fixtureId

Header

Mostrar:

Competition
Round
Kickoff
Status

Home Team
vs
Away Team

Probability Hero

Visualiza:

HOME
DRAW
AWAY

con comparación entre:

MODEL
MARKET

No uses únicamente una gráfica bonita.

Los números deben poder compararse rápidamente.

Market Intelligence

Tabla:

MarketSelectionModel ProbMarket ProbFair OddsBest OddsEdgeEV

Markets inicialmente:

1X2
Over / Under 2.5
BTTS
Double Chance

Team Intelligence

Comparación:

Elo
Form
Attack Rating
Defense Rating
Home/Away Strength
Goals
Schedule Strength

xG debe aparecer únicamente como:

Not Available

si todavía no existe fuente real.

Tabs

Implementa:

Overview
Markets
Models
Team Data
Timeline
Audit

Audit

Esta pestaña es crítica.

Representa la cadena:

Provider
  ↓
Raw Payload
  ↓
Normalized Fixture
  ↓
Feature Snapshot
  ↓
Prediction
  ↓
Odds Snapshot
  ↓
Decision

Mostrar campos conceptuales:

Prediction ID
Model
Model Version
Feature Version
Calibrator
Data Cutoff
Odds Snapshot
Captured At
Raw Payload Hash
Git SHA

Aunque sean DEMO, el diseño debe estar listo para datos reales.

4 — PICKS CENTER

URL:

/picks

No diseñes esta pantalla como una lista de “apuestas seguras”.

Debe parecer un decision intelligence system.

Estados:

CANDIDATE
SHADOW
QUALIFIED
PUBLISHED
SETTLED
REJECTED

Actualmente el producto debe enfatizar:

SHADOW MODE

Tabla de Picks

Columnas:

Fixture
Market
Selection
Model Probability
Market Probability
Fair Odds
Best Odds
Edge
EV
Reliability
Status
Timestamp

Pick Detail

Al seleccionar un pick abre panel lateral o página detallada.

Mostrar:

Why this candidate exists
Model
Model Version
Market Baseline
Model Probability
Market Probability
Fair Odds
Available Odds
Edge
Expected Value
Data Quality
Reliability
Risks
Odds Snapshot
Prediction Timestamp
Data Cutoff

No uses textos como:

BET NOW
GUARANTEED
SURE BET

5 — MODELS

URL:

/models

Debe sentirse como un Model Research Lab.

Mostrar siempre:

MARKET BASELINE

como primera referencia.

Después:

Elo
Poisson
Dixon-Coles
Logistic Regression
Gradient Boosting
Ensemble

Los modelos futuros pueden aparecer como:

NOT TRAINED
RESEARCH

Leaderboard

Columnas:

Model
Version
Status
Sample
Brier
Log Loss
Calibration Error
vs Market
ROI
CLV
Last Evaluation

ROI/CLV deben mostrarse:

—

si no existen datos suficientes.

Model Detail

Tabs:

Overview
Calibration
Performance
Leagues
Markets
Temporal Stability
Backtests
Versions

Calibration

Diseña visualización tipo:

Predicted Probability
vs
Observed Frequency

con diagonal ideal.

6 — PERFORMANCE

Diseña un módulo futuro con:

P&L
ROI
Yield
CLV / Line Value
Hit Rate
Drawdown
Bankroll
Sample Size

pero en DEMO deberá mostrar claramente:

Insufficient validated picks

7 — ODDS INTELLIGENCE

Preparar UX para:

Odds Explorer
Market Consensus
Line Movement
Value Scanner
Near-Close Snapshots

MUY IMPORTANTE

No utilizar todavía el término:

Closing Line
CLV

para nuestros snapshots T−12m como si estuvieran validados.

Nuestro dominio actual distingue:

Near-Close Snapshot

y:

Pick Line Value

hasta tener validación suficiente.

8 — DATA QUALITY

Esta pantalla es P0 para nosotros.

Debe mostrar:

Expected Fixtures
Available Fixtures
Fixtures With Odds
Market Coverage
Bookmaker Coverage
Stale Captures
Failed Jobs
Provider Errors
Unknown Teams
Missing Mapping
Last Successful Ingestion

Estados:

Healthy
Warning
Stale
Failed
Unknown

9 — AI ANALYST

No quiero un chatbot genérico.

Diseña la interfaz como research assistant conectado en el futuro a herramientas internas.

Ejemplos de preguntas sugeridas:

¿Por qué este pick tiene edge?

Compara Poisson contra el mercado en Premier League.

¿Qué modelos están peor calibrados?

¿Dónde cayó nuestro line value esta semana?

Muéstrame partidos con desacuerdo fuerte entre modelo y mercado.

Toda respuesta futura deberá basarse en datos estructurados.

COMPONENT LIBRARY

Construye componentes reutilizables.

Necesitamos como mínimo:

Sidebar
Topbar
PageHeader
Breadcrumb
Tabs
Search
FilterBar
Button

MetricCard
StatusBadge
ModelBadge
ResultBadge
DataFreshness

DataTable
SortableHeader
Pagination
EmptyState

TeamBadge
FixtureRow
CompetitionBadge
FormStrip

ProbabilityBar
ProbabilityComparison

OddsCell
FairOddsCell
EdgeIndicator
EVIndicator
LineValueIndicator

PickRow
PickCard

ChartContainer
CalibrationChart
EquityCurve
DrawdownChart

ProvenanceChip
AuditTimeline

Skeleton
ErrorState
WarningBanner

COMPONENT STATES

Cuando tengan sentido:

default
hover
active
selected
focus
disabled
loading
empty
error
warning
stale

No construyas únicamente el estado feliz.

RESPONSIVE

Optimiza primero para:

1440px desktop

pero implementa comportamiento real para:

1280
1024
768
390

En móvil:

las tablas complejas pueden transformarse en cards;

filtros pueden abrirse en drawer;

sidebar puede convertirse en menú;

información secundaria puede ir a drill-down;

no hagas scroll horizontal gigantesco como solución principal.

UX

Prioriza:

SCANABILITY
INFORMATION HIERARCHY
COMPARABILITY
TRACEABILITY
DATA TRUST

antes que decoración.

Quiero que el usuario pueda responder en segundos:

¿Qué partido importa?
¿Qué dice nuestro modelo?
¿Qué dice el mercado?
¿Existe edge?
¿Tenemos precio?
¿La información es fresca?
¿Qué modelo produjo esto?
¿Podemos confiar en esta muestra?

FORMATO DE DATOS MOCK

Centraliza el mock data.

No escribas datos inventados directamente dentro de cada componente.

Crea una capa como:

src/mock/

o equivalente.

Después podremos reemplazar:

mock adapter

por:

FastAPI adapter

sin reescribir componentes.

API CLIENT

Crea desde ahora una capa conceptual:

src/lib/api/

con configuración:

API_BASE_URL

desde environment.

Aunque inicialmente utilice mock data.

Ejemplo de recursos futuros:

GET /health
GET /matches
GET /matches/:id
GET /picks
GET /models
GET /performance
GET /data-quality

No construyas un backend falso complejo dentro de Lovable.

TIPOS FRONTEND

Define TypeScript types claros para:

Fixture
Competition
Team
OddsSnapshot
Market
MarketProbability
Prediction
ModelSummary
PickCandidate
PerformanceSummary
DataQualityStatus
SystemHealth

No uses:

any

para resolver el dominio.

NOMENCLATURA CIENTÍFICA

Nunca mezcles:

Model Probability
Market Probability
Confidence

como si fueran equivalentes.

Nunca mezcles:

Accuracy
ROI

Nunca muestres:

Edge

si no existe:

Model Probability
+
Available Price

ESTADO GLOBAL ACTUAL DEL PRODUCTO

Representa visualmente que estamos en:

SHADOW / RESEARCH MODE

No en producción pública.

Puede existir un pequeño indicador global:

RESEARCH MODE

en la barra superior.

NO IMPLEMENTAR AHORA

No construyas:

pagos;

sportsbook;

depósitos;

retiros;

apuestas automáticas;

login público complejo;

suscripciones;

afiliados;

marketplace;

casino;

integración directa con casas de apuestas;

ML real;

algoritmos de predicción;

un backend paralelo en Supabase.

PRIMER RESULTADO ESPERADO DE LOVABLE

En esta primera ejecución quiero que produzcas:

Foundation

app shell;

sidebar;

topbar;

design tokens;

typography;

routing;

responsive foundation;

mock data architecture;

API abstraction.

High Fidelity

Overview;

Match Center;

Picks;

Models.

Scaffold

Matches;

Odds;

Performance;

Backtesting;

Analytics;

Competitions;

Teams;

Rankings;

AI Analyst;

Data Quality;

Settings.

CRITERIOS DE CALIDAD

El resultado debe sentirse como una combinación de:

SPORTS DATA TERMINAL
+
QUANT RESEARCH PLATFORM
+
MODERN FOOTBALL INTELLIGENCE PRODUCT

y NO como:

generic betting website

Debe priorizar:

precisión;

coherencia;

modularidad;

profesionalismo;

excelente UX;

velocidad visual;

datos densos bien organizados;

componentes reutilizables;

responsive real;

accesibilidad;

future API integration.

RESTRICCIONES

No uses Supabase como dependencia.

No inventes backend productivo.

No inventes rentabilidad.

No presentes datos demo como reales.

No diseñes estilo casino.

No utilices llamadas agresivas a apostar.

No prometas ganancias.

No conviertas cada dato en una card.

No ocultes estados sin datos.

No utilices colores únicamente para transmitir significado.

No mezcles probability/confidence/edge.

No utilices any indiscriminadamente.

No dupliques componentes que puedan reutilizarse.

No implementes microservicios.

No añadas funcionalidades que no pertenezcan a esta fase.

INSTRUCCIÓN FINAL

Construye esta primera versión como si posteriormente fuera a conectarse directamente a nuestro FastAPI + PostgreSQL real, pero utilizando por ahora una capa de datos DEMO intercambiable.

Empieza por la arquitectura general + design system + app shell y después desarrolla las cuatro pantallas principales con calidad de producto real:

OVERVIEW
MATCH CENTER
PICKS CENTER
MODELS

No hagas una landing page.

Quiero entrar directamente al producto y sentir que estoy abriendo una herramienta profesional de inteligencia futbolística.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/c9094d86-2029-4e44-bd94-8d0ac13c47d4).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```

## Local development against the V2 backend

The app reads the product API of `football-intelligence-v2` (`VITE_API_BASE_URL`,
default `http://localhost:8010`) in the mode `VITE_DATA_MODE` sets - `live`,
`hybrid` or `mock`, see `.env.example`. The API-Football key never reaches the
browser: the web app only ever talks to that API.

```sh
bun install
bun run dev            # http://localhost:5173
```

Or start API, worker and web together from the backend repository with
`scripts/dev-up` (and stop them with `scripts/dev-down`).

## Checks

```sh
bun run lint           # eslint + prettier
bun run typecheck      # the app and the e2e suite
bun run build
bun run test:e2e       # Playwright, against the RUNNING stack
```

`e2e/` clicks through Overview → Match Center, Matches → Match, Odds → Match,
Models, Picks and Data Quality, and loads every route at 1440, 1280, 1024, 768
and 390 px. A page fails on a leaked `NaN`, `undefined`, `[object Object]` or
`Infinity`, a horizontal page scroll, a skeleton still loading once the network
is idle, a console or page error, or a failed API call. It seeds and mocks
nothing: where the database is too thin for a step (no captured prices yet),
the test records a `data` annotation instead of pretending.

For a run, start the API with `FBI_API_RATE_LIMIT=5000` (a full run is ~100
page loads), and install the browser once with `bunx playwright install chromium`.
`E2E_BASE_URL` and `E2E_API_URL` point the suite elsewhere.
