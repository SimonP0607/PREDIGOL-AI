/// <reference types="bun" />
/**
 * AP-T02 (audit K4, E2, A3): what the server writes for a reader is checked before it is drawn. A rumour or a sentence
 * in a script the reader does not read is not shown; a decimal with a point inside a Spanish sentence is written with a
 * comma. English text is left alone.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "./index";
import { localizeServerText, readerLines } from "./format";

afterEach(() => setLocale("es"));

// the text of the capture of the audit (K4): a rumour in Arabic inside a pick's reason
const ARABIC = "شائعات عن إصابة لاعب الارتكاز الأساسي قبل المباراة";

describe("localizeServerText", () => {
  test("a text in Arabic is not drawn, in either language", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      expect(localizeServerText(ARABIC)).toBeNull();
      expect(localizeServerText(`El equipo llega bien. ${ARABIC}`)).toBeNull();
    }
  });

  test("other scripts too: Cyrillic, Hebrew, Han, Thai", () => {
    for (const text of ["Травма игрока", "פציעה של שחקן", "球员受伤", "นักเตะบาดเจ็บ"]) {
      expect(localizeServerText(text), text).toBeNull();
    }
  });

  test("a rumour is not drawn", () => {
    setLocale("es");
    expect(localizeServerText("Según rumores, el delantero no jugaría")).toBeNull();
    expect(localizeServerText("Se rumorea una lesión")).toBeNull();
    expect(localizeServerText("Rumour of a late injury")).toBeNull();
    // an unconfirmed lineup is a risk the review found, not a rumour: it is drawn
    expect(localizeServerText("Alineaciones sin confirmar")).toBe("Alineaciones sin confirmar");
  });

  test("«0.473» does not appear: the decimal is written with the language's format", () => {
    setLocale("es");
    expect(localizeServerText("El modelo da 0.473 a la selección")).toBe(
      "El modelo da 0,473 a la selección",
    );
    expect(localizeServerText("La probabilidad es 73.7 % frente a 68.2 %")).toBe(
      "La probabilidad es 73,7 % frente a 68,2 %",
    );
    expect(localizeServerText("0.473")).not.toContain("0.473");
  });

  test("what is not a decimal stays: a version, a date, thousands, words with a point", () => {
    setLocale("es");
    expect(localizeServerText("Versión 1.2.3 del modelo")).toBe("Versión 1.2.3 del modelo");
    expect(localizeServerText("Hasta 4.000 caracteres")).toBe("Hasta 4.000 caracteres");
    expect(localizeServerText("Lo vio el 12.11.2026 en el estadio")).toBe(
      "Lo vio el 12.11.2026 en el estadio",
    );
    expect(localizeServerText("Ya llegó. Ahora juega")).toBe("Ya llegó. Ahora juega");
  });

  test("accents, ñ and the euro sign are Latin text: they stay", () => {
    setLocale("es");
    const text = "El técnico confía en el niño de 17 años: señal de 1,5 goles.";
    expect(localizeServerText(text)).toBe(text);
  });

  test("English keeps its point", () => {
    setLocale("en");
    expect(localizeServerText("The model gives 0.473 to the selection")).toBe(
      "The model gives 0.473 to the selection",
    );
  });

  test("empty text is nothing", () => {
    expect(localizeServerText("   ")).toBeNull();
    expect(localizeServerText(null)).toBeNull();
    expect(localizeServerText(undefined)).toBeNull();
  });

  test("a list keeps the good lines, in order, and drops the others", () => {
    setLocale("es");
    expect(
      readerLines(["Llega con 0.5 goles de ventaja", ARABIC, "Sin bajas", "Se rumorea un cambio"]),
    ).toEqual(["Llega con 0,5 goles de ventaja", "Sin bajas"]);
    expect(readerLines(null)).toEqual([]);
  });

  // 30 reasons as the server writes them today (Spanish, English, with numbers): none is hidden by mistake
  test("30 real reasons are not hidden by the guard", () => {
    setLocale("es");
    const reasons = [
      "El mercado paga 2.10 y PrediGol estima 52 %",
      "Lleva cuatro victorias seguidas como local",
      "Sin bajas confirmadas en el once titular",
      "El rival juega tres partidos en siete días",
      "Cuota estable en las últimas 24 horas",
      "Las dos defensas tienen pocos goles encajados",
      "Muestra de 18 partidos con ese patrón",
      "Árbitro con media de 5,2 tarjetas por partido",
      "Viaja tras una semana de descanso",
      "El portero titular regresa de sanción",
      "La cuota bajó de 2.30 a 2.05 desde la apertura",
      "Historial reciente: 3 victorias, 1 empate y 1 derrota",
      "Racha de 5 partidos sin perder",
      "Clima seco, campo en buen estado",
      "Clásico con tendencia a pocos goles",
      "Más de 2.5 goles en 7 de los últimos 10",
      "Lesión confirmada del delantero suplente",
      "Rotaciones previstas por la copa de la semana siguiente",
      "El equipo no pierde en casa desde marzo",
      "Empate frecuente en este cruce",
      "Probabilidad del mercado sin margen: 48.5 %",
      "Ventaja de 4.2 puntos porcentuales sobre el mercado",
      "Un equipo con la defensa más sólida de la liga",
      "Sin datos de alineación todavía",
      "Local con 11 partidos sin recibir más de un gol",
      "El visitante marca poco fuera de casa",
      "Línea de 2.75 goles con movimiento leve",
      "Partido de máxima importancia para la clasificación",
      "Diferencia de 12 puestos en la tabla",
      "Convocatoria completa, sin dudas físicas",
    ];
    expect(reasons).toHaveLength(30);
    for (const r of reasons) expect(localizeServerText(r), r).not.toBeNull();
    // and the ones with a decimal read in Spanish
    expect(localizeServerText(reasons[0]!)).toBe("El mercado paga 2,10 y PrediGol estima 52 %");
    expect(localizeServerText(reasons[10]!)).toBe("La cuota bajó de 2,30 a 2,05 desde la apertura");
  });
});
