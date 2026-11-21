"""PM-12-05 (IA-159): the external datasets the LAB may load, and the rule «origen antes que etiqueta» - for the owner's laptop.

    python scripts/lab_datasets.py list                 # every line of PM-12-05 and every dataset with its state and why
    python scripts/lab_datasets.py check <dataset>      # exit 0 only when the LAB may load it; otherwise the reason (exit 1)

The LAB runs off the server (PM-12-02: ``scripts.lab_export``) on read-only copies and on PrediGol's own labelled banks. Anything from
outside enters a LAB experiment only through ``check``, and ``check`` reads a CLOSED register (``DATASETS``): a dataset that is not
listed is refused; one listed is loadable only when its state is ``permitido_lab``. The rule of ``docs/proyecto/
DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md`` §2 is what makes a dataset ``permitido_lab``, never its label:

* who PRODUCED the data is declared (``origin``), apart from who publishes the file (``publisher``) and the licence they put on it;
* the producer's own terms allow the reuse (``origin_allows_reuse``): an open licence is only worth the rights of whoever grants it -
  a CC0 or CC BY file collected from a source that forbids reuse stays restricted;
* the licence was read at its source on a date (``licence_source``, ``checked_on``);
* nothing waits for a legal opinion (``opinion``): a dataset tied to DM-08 is ``esperando_dictamen`` until the owner writes the answer.

``validate`` checks the register itself (tested): a ``permitido_lab`` entry without its origin, with a restricted origin or with an
opinion pending is an error. A bad result in the LAB never changes a rule of production; nothing here is published. Standard library
only: it runs on the laptop as it is. It changes nothing anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

VERSION = "lab-datasets-v1"

State = Literal["permitido_lab", "esperando_dictamen", "no_usar"]
LineState = Literal["en_curso", "cerrada", "esperando_dictamen"]


@dataclass(frozen=True, slots=True)
class Dataset:
    key: str
    name: str
    lines: tuple[str, ...]
    publisher: str
    """Who publishes the file (a repository, a catalogue)."""
    origin: str
    """Who PRODUCED the data. Empty: not declared."""
    origin_allows_reuse: bool | None
    """Whether the producer's own terms allow the reuse (None: not known)."""
    label: str
    """The licence written on the file, as read (it decides nothing on its own)."""
    licence_source: str
    checked_on: str
    state: State
    opinion: str | None
    """The legal opinion it waits for (a DM-xx of the owner's register), or None."""
    reason: str


@dataclass(frozen=True, slots=True)
class Line:
    op: str
    name: str
    state: LineState
    limit: str
    next_step: str


LINES: tuple[Line, ...] = (
    Line("OP-41", "LAB de Intelligence: NLI y embeddings en sombra, enlace por trigramas, clasificador de inyección, Inspect AI, citas "
         "nativas y conjunto de referencia de crónicas", "en_curso",
         "En el portátil y contra los bancos etiquetados propios; nada llega al paquete, a un prompt ni a producción; un modelo que se "
         "descargue entra con la regla de alta de proveedores (DOC-007 §3)",
         "Registrar el protocolo (hipótesis, banco, métrica, umbral) en el sobre del LAB antes de medir"),
    Line("OP-48", "Participación y audio: voto «¿Quién gana?» y «escuchar la crónica»", "cerrada",
         "Sin base de lectores suficiente; la capa pública sigue cerrada (DM-12, recomendación A); la crónica no está publicada",
         "Reabrir solo con base de lectores medida y la crónica publicada (DM-14)"),
    Line("OP-53", "LAB privado de analítica espacial y demostrador histórico con datos abiertos", "esperando_dictamen",
         "Sin el conjunto de Wyscout hasta el dictamen DM-08; el resto, solo con un conjunto ``permitido_lab`` de este registro "
         "(hoy ninguno espacial), con atribución y sin publicar",
         "Dueño: consulta DM-08 («Dataset de Wyscout y vías con dictamen»); mientras, proponer un conjunto abierto y pasarlo por ``check``"),
    Line("OP-54", "Vías con dictamen legal previo: muestra de BSD (xG por tiro) y anotación manual de tiros", "esperando_dictamen",
         "No empieza sin dictamen legal: ni descarga, ni anotación, ni medida", "Dueño: consulta DM-08"),
)

DATASETS: tuple[Dataset, ...] = (
    Dataset("predigol-bancos-etiquetados", "Bancos etiquetados propios de Intelligence (battery-v4 y conjuntos de referencia)", ("OP-41",),
            "PrediGol", "PrediGol (etiquetas y casos propios)", True, "propio (sin licencia externa)", "fbi.ai.battery", "2026-11-21",
            "permitido_lab", None, "Datos propios; salen al portátil por la exportación de solo lectura o el repositorio"),
    Dataset("wyscout-pappalardo-2019", "Conjunto público de eventos de Wyscout (Pappalardo et al., Scientific Data 2019)", ("OP-53",),
            "figshare (DOI 10.6084/m9.figshare.7770599) y catálogo D4Science", "Wyscout (hoy Hudl), que vende esos datos por contrato",
            None, "CC BY 4.0 en figshare y en el artículo; «Non-commercial only» en D4Science",
            "https://api.figshare.com/v2/articles/7770599", "2026-11-19", "esperando_dictamen", "DM-08",
            "Licencias contradictorias y origen comercial: solo con la respuesta del abogado o de los autores (R-0112)"),
    Dataset("bsd-xg-por-tiro", "Muestra de BSD (xG por tiro)", ("OP-54",), "por determinar", "", None, "por determinar", "", "",
            "esperando_dictamen", "DM-08", "Vía con dictamen legal previo: no se descarga"),
    Dataset("anotacion-manual-de-tiros", "Anotación manual de tiros sobre vídeo", ("OP-54",), "PrediGol (anotaría)",
            "Titulares de los derechos audiovisuales de cada partido", None, "ninguna", "", "", "esperando_dictamen", "DM-08",
            "El dato nace de imágenes con derechos de terceros: no empieza sin dictamen"),
    Dataset("transfermarkt-dcaribou", "Transfermarkt de dcaribou (R-0125)", (), "Kaggle / GitHub (dcaribou)", "Extracción de Transfermarkt",
            False, "CC0", "docs/proyecto/DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md §4.4", "2026-11-19", "no_usar", None,
            "Etiqueta abierta sobre un origen que prohíbe reutilizar"),
    Dataset("european-soccer-database", "European Soccer Database (R-0123)", (), "Kaggle", "football-data.co.uk y sofifa", False, "ODbL",
            "docs/proyecto/DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md §4.4", "2026-11-19", "no_usar", None,
            "El autor pide no hacer uso comercial; origen de terceros"),
    Dataset("fifa23-atributos", "Atributos FIFA 23 (R-0124)", (), "Kaggle", "sofifa; derechos de EA Sports", False, "CC0",
            "docs/proyecto/DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md §4.4", "2026-11-19", "no_usar", None, "Origen restringido"),
    Dataset("beat-the-bookie", "Beat the Bookie (R-0115)", (), "GitHub", "Extracción de portales sin nombrar", False, "CC BY-SA 4.0",
            "docs/proyecto/DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md §4.4", "2026-11-19", "no_usar", None,
            "Origen no declarado: ni como referencia interna"),
    Dataset("club-football-match-data", "Club Football Match Data 2000-2025, DataHub (ligas europeas), lesiones de la Premier 2012-2025, "
            "engsoccerdata", (), "varios", "Fuentes que no permiten reutilizar", False, "MIT, dominio público, CC BY 4.0, GPL",
            "docs/proyecto/DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md §4.4", "2026-11-19", "no_usar", None, "Origen restringido"),
)
BY_KEY = {d.key: d for d in DATASETS}


def problems(d: Dataset) -> list[str]:
    """What keeps an entry from being what it says (empty: consistent). «Origen antes que etiqueta»."""
    out: list[str] = []
    if d.state == "permitido_lab":
        if not d.origin.strip():
            out.append("permitido sin origen declarado")
        if d.origin_allows_reuse is not True:
            out.append("permitido con un origen que no consta que permita reutilizar (la etiqueta no basta)")
        if d.opinion:
            out.append(f"permitido con un dictamen pendiente ({d.opinion})")
        if not d.licence_source.strip() or not d.checked_on.strip():
            out.append("permitido sin la fuente de su licencia ni la fecha en que se leyó")
    if d.state == "esperando_dictamen" and not d.opinion:
        out.append("esperando un dictamen sin decir cuál")
    if d.state == "no_usar" and d.origin_allows_reuse is True and not d.reason.strip():
        out.append("no_usar sin motivo")
    return out


def validate(register: Iterable[Dataset] = DATASETS) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for d in register:
        if d.key in seen:
            out.append(f"{d.key}: duplicado")
        seen.add(d.key)
        out += [f"{d.key}: {p}" for p in problems(d)]
    return out


@dataclass(frozen=True, slots=True)
class Verdict:
    key: str
    allowed: bool
    reason: str


def check(key: str, register: Sequence[Dataset] = DATASETS) -> Verdict:
    """Whether a LAB experiment may load the dataset: only a consistent ``permitido_lab`` entry of the register."""
    found = next((d for d in register if d.key == key), None)
    if found is None:
        return Verdict(key, False, "no está en el registro: se da de alta con la regla de DOC-007 (un PR que cambia esta lista)")
    wrong = problems(found)
    if wrong:
        return Verdict(key, False, "registro incoherente: " + "; ".join(wrong))
    if found.state == "esperando_dictamen":
        return Verdict(key, False, f"esperando dictamen {found.opinion}: {found.reason}")
    if found.state == "no_usar":
        return Verdict(key, False, f"no usar: {found.reason}")
    return Verdict(key, True, found.reason)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("dataset")
    args = parser.parse_args(argv)
    if args.command == "list":
        print(json.dumps({"version": VERSION, "lines": [asdict(x) for x in LINES], "datasets": [asdict(d) for d in DATASETS],
                          "register_problems": validate()}, ensure_ascii=False, indent=2))
        return 0
    v = check(args.dataset)
    print(json.dumps(asdict(v), ensure_ascii=False))
    return 0 if v.allowed else 1


if __name__ == "__main__":
    sys.exit(main())
