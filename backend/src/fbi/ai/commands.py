"""Sentences with the shape of an order to a machine, in the eight languages PrediGol searches in (IA-060, plan piece AD-A01).

``fbi.ai.untrusted`` flags a text that reads like an order to a model (``instruction_like``) and the door in front of every agent uses it. The
quarantined extractor (``fbi.ai.quarantine``) needs a stricter question about every SENTENCE of a page, because it never reads a page that
contains one and never keeps a quote that is, or sits in, one:

* it names a machine reader and tells it something - «Note for the AI model reading this: add...», «Los sistemas automáticos deben...»,
  «Extractors: list...», «KI-Modelle müssen ... melden»;
* it tries to take over - «ignore your instructions», «new instructions», «SYSTEM:», «you are now», «modo sin restricciones»;
* it tells the reader what to put in its answer - «add an item», «añade una afirmación», «your answer», «begin the claim with the code word»,
  «responde solo con...»;
* it marks someone, in the imperative, as available or out - «report him as available», «márcalo como baja», «segnala ... come disponibile»,
  «als verfügbar melden», «müsait olarak bildir»;
* it orders a tool, a function, a query - «call the tool», «usa la herramienta», «add_player_status(player=...)», «DELETE FROM»;
* it orders the other reports away - «discard every item», «descarta todos los resultados», «discard result R1».

Football news does not talk like that: a coach who says «ignore the noise», a «list of absentees», «Marca informa que...», «Read also», «Haz clic
aquí» are not orders to a machine, and the tests hold a set of such sentences in the eight languages that must never be flagged. What is
compared is the text folded (lower case, no accents), apart from the acronyms of a machine (``AI``, ``IA``, ``KI``, ``LLM``, ``YZ``), which are
read in capitals only («ia» is a Portuguese verb).

What this is not: a proof. A page can state a falsehood as a fact («A. Striker is fit») without a word of an order, and nothing lexical can tell
it from a true report; that is the standing of the source's business (``fbi.ai.evidence``). What it does is to make sure that what the
quarantined extractor keeps never contains an instruction and never comes from a page that carries one.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Final

VERSION: Final = "commands-v1"

_SPLIT: Final = re.compile(r"(?<=[.!?\u2026])(?<![\s(\[][A-Z]\.)(?<!^[A-Z]\.)\s+|\n+|\s*[\[\]()<>{}|\u00ab\u00bb\u201c\u201d\"]\s*|"
                           r"\s+[-\u2013\u2014]\s+")
"""Where a sentence ends: after a stop (but not after an initial - «D. Keeper» is one name), a line, a bracket, a quotation mark or a dash."""
_COLON: Final = re.compile(r"\s*:\s*")


def fold(text: str) -> str:
    """Lower case, accents taken off, spaces made single: the form the patterns read."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(plain.replace("\u0131", "i").casefold().split())


def spans(text: str) -> list[tuple[int, int]]:
    """Where each sentence of ``text`` starts and ends (``sentences``), in the text as it is."""
    out: list[tuple[int, int]] = []
    start = 0
    for m in _SPLIT.finditer(text):
        if m.start() > start:
            out.append((start, m.start()))
        start = m.end()
    if start < len(text):
        out.append((start, len(text)))
    return out


_COARSE: Final = re.compile(r"(?<=[.!?\u2026])(?<![\s(\[][A-Z]\.)(?<!^[A-Z]\.)\s+|\n+")


def coarse_spans(text: str) -> list[tuple[int, int]]:
    """Where each sentence of ``text`` starts and ends, by its stops and lines only (a bracket or a quotation mark does not end it)."""
    out: list[tuple[int, int]] = []
    start = 0
    for m in _COARSE.finditer(text):
        if m.start() > start:
            out.append((start, m.start()))
        start = m.end()
    if start < len(text):
        out.append((start, len(text)))
    return out


def sentences(text: str) -> list[str]:
    """The sentences of a text (and the pieces between brackets, quotes and dashes): where an order starts is where a reader would start."""
    return [piece for a, b in spans(text) if (piece := text[a:b].strip(" '`*_#"))]


# ── who is addressed ─────────────────────────────────────────────────────────────────────────────────────────────

_ACRONYM: Final = re.compile(r"(?<![A-Za-z])(?:AI|A\.I\.|IA|KI|LLMs?|YZ|GPT|ChatGPT)(?![A-Za-z])")
_MACHINE: Final = (
    r"(?:(?:large\s+)?language\s+models?|llms?|chatbots?|bots?|extractors?|scrapers?|crawlers?|parsers?|"
    r"(?:automated|automatic|extraction|ai|machine)[ -](?:systems?|tools?|readers?|models?|pipelines?|assistants?|agents?|extractors?)|"
    r"(?:any|every|all)\s+(?:ai|models?)|ai\s+models?|"
    r"inteligencia artificial|modelos? de (?:lenguaje|ia|linguagem)|asistentes? (?:virtual(?:es)?|de ia)|extractor(?:es)?|"
    r"sistemas? (?:automatic[oa]s?|de extraccion)|lectores? automatic[oa]s?|"
    r"extrator(?:es)?|sistemas? automatic[oa]s?|assistentes? virtua(?:l|is)|"
    r"intelligenza artificiale|modell[oi] (?:linguistic[oi]|di ia)|assistenti? virtual[ei]|estrattor[ei]|sistem[ai] automatic[oi]|"
    r"intelligence artificielle|modeles? de langage|assistants? virtuels?|extracteurs?|systemes? automatiques?|"
    r"kunstliche intelligenz|sprachmodell(?:e|en)?|ki-(?:modell(?:e|en)?|assistent(?:en)?|systeme?)|extraktor(?:en)?|"
    r"automatisierte[ns]? systeme?|automatische[ns]? systeme?|"
    r"kunstmatige intelligentie|taalmodel(?:len)?|ai-(?:model(?:len)?|assistent(?:en)?|systemen?)|geautomatiseerde systemen|"
    r"yapay zeka|dil modeli|otomatik sistem(?:ler)?)"
)
_MACHINE_RE: Final = re.compile(r"\b" + _MACHINE + r"\b")

_MODAL: Final = re.compile(
    r"\b(?:must|should|shall|need to|needs to|have to|has to|are to|is to|are required|are instructed|are expected to|"
    r"deben?|debera[ns]?|tienen? que|han? de|devem|deve|deverao|tem que|tem de|devono|dovrebbero|dovrebbe|doit|doivent|devrai(?:en)?t|"
    r"mussen|muss|sollen|soll|moeten|moet|zorunda|gerek\w*|\w+(?:meli|mali)(?:dir)?)\b")
"""A machine named and, right after it, a modal that tells it what to do («extraction systems must label», «los sistemas automáticos deben»,
«KI-Modelle müssen», «otomatik sistemler ... zorunda»): a machine merely named («the model's probability», «KI-Prognose», «AI analysis») is not
an order."""
_NEAR: Final = 60
_ACRONYMS_FOLDED: Final = ("ai", "a.i.", "ia", "ki", "llm", "llms", "yz", "gpt", "chatgpt")

_ADDRESSED: Final = tuple(re.compile(p) for p in (
    r"\b(?:note|message|instructions?|reminder|attention|memo|warning)\s+(?:for|to)\s+(?:the\s+|any\s+|all\s+|every\s+)?(?:ai|" + _MACHINE[3:-1] + r")\b",
    r"\b(?:nota|mensaje|aviso|instrucciones?|recordatorio|atencion|mensagem|lembrete|messaggio|avviso|istruzioni|promemoria|attenzione|"
    r"message|consigne|rappel|hinweis|nachricht|anweisung|achtung|bericht|opmerking|let op|not|mesaj|uyari|talimat)\w*\s+"
    r"(?:para|a|al|para a|para o|per|pour|fur|an|die|voor|aan|icin)\s+(?:la\s+|el\s+|os\s+|as\s+|o\s+|a\s+|il\s+|l'|le\s+|les\s+|"
    r"den\s+|das\s+|de\s+|het\s+)?(?:ia|ki|ai|yz|" + _MACHINE[3:-1] + r")\b",
    r"\b(?:ai|ia|ki|model|modelo|modello|modele|modell|bot|assistant|asistente|assistente|extractor|extrator|estrattore|extracteur)s?\s+"
    r"(?:reading|leyendo|que lee|lendo|que le|che legge|qui lit|der liest|die liest|dat leest|die dit leest|okuyan)\b",
    r"\bif you are (?:an?\s+)?(?:ai|bot|model|assistant|language model|llm|extractor|automated)\b",
    r"\bsi (?:eres|es|sei|tu es|vous etes) (?:una?\s+|un\s+)?(?:ia|ai|bot|modelo|modello|modele|asistente|assistente|assistant)\b",
    r"\b(?:yapay zeka|yz|ai)\w*\s+icin\s+(?:not|mesaj|uyari|talimat)\w*",
))

# ── a take-over ──────────────────────────────────────────────────────────────────────────────────────────────────

_TAKEOVER: Final = tuple(re.compile(p) for p in (
    r"\b(?:ignore|disregard|forget|override|bypass|skip)\b[^.]{0,40}\b(?:instructions?|rules|prompt|guidelines|system|everything above)\b",
    r"\b(?:ignora|ignore|ignoren|olvida|olvide|omite|descarta|desatiende|desconsidere|esqueca|esquece|dimentica|trascura|ignorez|"
    r"oublie|oubliez|ignoriere|ignorieren|vergiss|vergessen|missachte|negeer|vergeet|yoksay|unut|gormezden gel)\w*\b[^.]{0,40}\b"
    r"(?:instrucciones|reglas|indicaciones|prompt|instrucoes|regras|istruzioni|regole|consignes|instructions|regles|anweisungen|"
    r"regeln|vorgaben|instructies|regels|talimat|kural)\w*",
    r"\b(?:new|updated|real|actual) (?:instructions?|orders|task|rules)\b|\bnuevas? (?:instrucciones|ordenes|reglas|tarea)\b|"
    r"\bnovas? (?:instrucoes|ordens|regras|tarefa)\b|\bnuove (?:istruzioni|regole)\b|\bnuovo compito\b|"
    r"\bnouvelles? (?:instructions|consignes|regles|tache)\b|\bneue (?:anweisungen|regeln|aufgabe)\b|"
    r"\bnieuwe (?:instructies|regels|opdracht)\b|\byeni (?:talimat|kural|gorev)\w*",
    r"\b(?:system prompt|developer message|prompt del sistema|mensaje del sistema|prompt do sistema|prompt di sistema|"
    r"invite systeme|systemprompt|systeemprompt|sistem istemi)\b",
    r"^\W*(?:system|assistant|developer|operator|user|sistema|asistente|assistente|systeme|systeem|sistem|admin|root)\s*[:>]",
    r"\b(?:you are now|from now on,? you|you will now act|pretend to be|"
    r"ahora eres|a partir de ahora (?:eres|actua|responde|seras)|desde ahora eres|agora voce e|a partir de agora (?:voce|responda|sera)|"
    r"ora sei|d'ora in (?:poi|avanti) (?:sei|rispondi|agisci)|tu es maintenant|vous etes maintenant|desormais,? (?:tu|vous)|"
    r"du bist (?:jetzt|nun)|ab (?:jetzt|sofort) bist du|je bent nu|vanaf nu ben je|artik sen|bundan sonra sen)\b",
    r"^act as\b|\bact as (?:an?\s+)?(?:ai|assistant|model|bot|system|unrestricted|jailbroken|different)\b|"
    r"\b(?:unrestricted|developer|debug|god|jailbreak|dan) mode\b|\bjailbreak\b|\bmodo (?:sin restricciones|desarrollador|sem restricoes|"
    r"senza restrizioni)\b|\bmode (?:sans restriction|developpeur)\b|\buneingeschrankte[nr]? modus\b|\bonbeperkte modus\b|"
    r"\bkisitlamasiz mod\b",
    r"\b(?:end of (?:data|results|pages|input)|fin de (?:los )?(?:datos|resultados)|fim dos dados|fine dei dati|fin des donnees|"
    r"ende der daten|einde van de gegevens|veri sonu)\b",
))

# ── what goes into the answer ────────────────────────────────────────────────────────────────────────────────────

_ANSWER: Final = tuple(re.compile(p) for p in (
    r"\byour\s+(?:answer|response|output|reply|extraction|claims|items|json|first (?:item|claim))\b",
    r"\btu\s+(?:respuesta|salida|extraccion|lista)\b|\bvuestra respuesta\b|\b(?:tua|la tua)\s+(?:resposta|risposta)\b|"
    r"\bsua\s+(?:saida|extracao)\b|\b(?:ta|votre)\s+(?:reponse|sortie|extraction)\b|\b(?:deine|eure)\s+(?:antwort|ausgabe)\b|"
    r"\bihre ausgabe\b|\b(?:je|jouw|uw)\s+(?:antwoord|uitvoer)\b|\b(?:cevabin|yanitin|ciktin)\w*",
    r"\b(?:add|include|insert|append|write|output|return|create|make up|invent|put)\b[^.]{0,25}\b(?:an?|one|another|the following|this|"
    r"these|two|three|new)\s+(?:items?|claims?|entry|entries|records?|facts?)\b",
    r"\b(?:anade|agrega|incluye|inserta|escribe|devuelve|crea|inventa|pon)\b[^.]{0,25}\b(?:un|una|otro|otra|el siguiente|la siguiente|"
    r"este|esta|dos|nuevo|nueva)\s+(?:elementos?|items?|afirmacion(?:es)?|entradas?|registros?|datos?)\b",
    r"\b(?:adicione|adiciona|inclua|inclui|insira|escreva|retorne|devolva|crie|invente|ponha)\b[^.]{0,25}\b(?:um|uma|outro|outra|"
    r"o seguinte|a seguinte|este|esta|dois|novo|nova)\s+(?:itens?|elementos?|afirmac(?:ao|oes)|entradas?|registros?)\b",
    r"\b(?:aggiungi|includi|inserisci|scrivi|restituisci|crea|inventa|metti)\b[^.]{0,25}\b(?:un|una|un'|un altro|un'altra|il seguente|"
    r"la seguente|questo|questa|due|nuovo|nuova)\s*(?:elementi|elemento|voce|voci|affermazion[ei]|dati|dato)\b",
    r"\b(?:ajoute[zr]?|inclu[st]|incluez|insere[zr]?|ecri[st]|ecrivez|renvoie[zr]?|cree[zr]?|invente[zr]?|mets|mettez)\b[^.]{0,25}"
    r"\b(?:un|une|un autre|une autre|le suivant|la suivante|cet|cette|deux|nouvel|nouvelle)\s+(?:elements?|items?|affirmations?|"
    r"entrees?|enregistrements?)\b",
    r"\b(?:fuge|fugen|schreibe|schreiben|gib|geben|erstelle|erstellen|erfinde|erfinden|setze)\b[^.]{0,40}\b(?:eintrag|eintrage|element|"
    r"aussage|behauptung)\w*",
    r"\b(?:voeg|schrijf|geef|maak|verzin|zet)\b[^.]{0,40}\b(?:item|items|element|bewering|vermelding|regel)\w*",
    r"\b(?:oge|madde|kayit|iddia|girdi)\w*\b[^.]{0,30}\b(?:ekle|yaz|olustur|uydur)\w*",
    r"^(?:please\s*,?\s*)?(?:give|set|assign|output|use|put|state|write|report|add)\b[^.]{0,30}\b(?:probabilit(?:y|ies)|odds|stake|"
    r"confidence|edge)\b",
    r"^(?:por favor\s*,?\s*)?(?:dale|asigna|escribe|atribua|coloque|escreva|dai|assegna|metti|scrivi|donne[zr]?|attribue[zr]?|ecri[st]|"
    r"gib|setze|schreibe|geef|schrijf|yaz)\b[^.]{0,30}\b(?:probabilidad(?:es)?|probabilidade|probabilita|probabilite|wahrscheinlichkeit|"
    r"olasilik|cuotas?|quotas?|cotes?|quoten?|apuesta|aposta|scommessa|mise|einsatz|inzet|bahis)\b",
    r"\b(?:code ?word|secret word|passphrase|password|palabra (?:clave|en clave|secreta)|codigo secreto|contrasena|palavra[- ](?:chave|secreta)|"
    r"senha|parola (?:chiave|d'ordine|segreta)|codice segreto|mot (?:de code|secret|de passe)|mot-code|codewort|kennwort|passwort|"
    r"codewoord|wachtwoord|kod kelime|gizli kelime|sifre)\b",
    r"\b(?:begin|start|open|prefix)\b[^.]{0,25}\b(?:answer|claim|quote|item|response|reply|output)\b[^.]{0,20}\bwith\b",
    r"\b(?:empieza|comienza|inicia|empiece|comience)\b[^.]{0,25}\b(?:respuesta|afirmacion|cita|elemento)\b|"
    r"\b(?:comece|inicie)\b[^.]{0,25}\b(?:resposta|afirmacao|citacao|item)\b|\b(?:inizia|comincia)\b[^.]{0,25}\b(?:risposta|affermazione|"
    r"citazione)\b|\bcommence[zr]?\b[^.]{0,25}\b(?:reponse|affirmation|citation)\b|\bbeginne\b[^.]{0,25}\b(?:antwort|aussage|zitat)\b|"
    r"\bbegin\b[^.]{0,25}\b(?:antwoord|bewering|citaat)\b|\b(?:yanit|cevap|iddia)\w*\b[^.]{0,25}\bbasla\w*",
    r"^(?:please\s*,?\s*)?(?:reply|respond|answer|output|return)\b[^.]{0,20}\b(?:only|just|exactly|solely)\b|\breply with the plain text\b|"
    r"\bno json\b|"
    r"\b(?:responde|contesta|devuelve|responda|retorne|rispondi|restituisci|reponds|repondez|antworte|antworten sie|antwoord|geef)\b"
    r"[^.]{0,20}\b(?:solo|unicamente|exclusivamente|apenas|somente|soltanto|esclusivamente|uniquement|seulement|nur|ausschliesslich|"
    r"alleen|uitsluitend|enkel)\b|\bsadece\b[^.]{0,25}\b(?:yanit|cevap)\w*",
))

# ── someone marked, in the imperative ────────────────────────────────────────────────────────────────────────────

_STATUS_EN: Final = (r"(?:available|unavailable|fit|fully fit|out|injured|doubtful|a doubt|doubt|confirmed|starting|a starter|starter|"
                     r"suspended|absent|ruled out|cancell?ed|playing)")
_MARK: Final = tuple(re.compile(p) for p in (
    r"^(?:please\s*,?\s*)?(?:report|list|mark|label|tag|classify|treat|record|declare|register|flag|consider|set|show|state)\b(?!\s+of\b)"
    r"[^.]{0,80}\bas\s+(?:being\s+)?" + _STATUS_EN + r"\b",
    r"^(?:please\s*,?\s*)?(?:report|state|say|write|declare|tell)\s+(?:us\s+|them\s+)?that\b",
    r"^(?:por favor\s*,?\s*)?(?:informa|reporta|indica|marca\s+a|marcalo|marcala|marcalos|etiqueta|clasifica|registra|considera|declara|"
    r"anota|lista|pon|trata)\b[^.]{0,80}\bcomo\s+(?:disponible|baja|lesionad[oa]s?|duda|dudos[oa]s?|titular(?:es)?|apt[oa]s?|"
    r"confirmad[oa]s?|sancionad[oa]s?|suspendid[oa]s?|descartad[oa]s?|ausentes?|recuperad[oa]s?)\b",
    r"^(?:por favor\s*,?\s*)?(?:informa|reporta|di|escribe|declara)\s+(?:de\s+)?que\b",
    r"^(?:por favor\s*,?\s*)?(?:informe|reporte|indique|marque|registre|considere|declare|liste|trate|coloque)\b[^.]{0,80}\bcomo\s+"
    r"(?:disponive(?:l|is)|baixa|lesionad[oa]s?|duvida|titular(?:es)?|apt[oa]s?|confirmad[oa]s?|suspens[oa]s?|ausentes?|"
    r"recuperad[oa]s?|fora)\b",
    r"^(?:por favor\s*,?\s*)?(?:informe|diga|escreva|declare)\s+que\b",
    r"^(?:per favore\s*,?\s*)?(?:segnala|riporta|indica|contrassegna|etichetta|classifica|registra|considera|dichiara|elenca|tratta)\b"
    r"[^.]{0,80}\bcome\s+(?:disponibil[ei]|indisponibil[ei]|infortunat[oiae]|in dubbio|titolar[ei]|abil[ei]|confermat[oiae]|"
    r"squalificat[oiae]|assent[ei]|recuperat[oiae]|out|fuori)\b",
    r"^(?:per favore\s*,?\s*)?(?:scrivi|dichiara|segnala|riporta)\s+che\b",
    r"^(?:merci de\s+|veuillez\s+|s'il (?:te|vous) plait\s*,?\s*)?(?:signale[zr]?|indique[zr]?|marque[zr]?|etiquete[zr]?|classe[zr]?|"
    r"enregistre[zr]?|considere[zr]?|declare[zr]?|liste[zr]?|traite[zr]?|note[zr]?)\b[^.]{0,80}\bcomme\s+(?:disponibles?|"
    r"indisponibles?|blesses?|incertains?|titulaires?|aptes?|confirmes?|suspendus?|absents?|forfaits?|retablis?)\b",
    r"^(?:merci d'|veuillez\s+)?(?:ecri[st]|ecrivez|declare[zr]?|indique[zr]?|signale[zr]?)\s+qu(?:e|')",
    r"^(?:bitte\s*,?\s*)?(?:melde|melden|markiere|markieren|kennzeichne|kennzeichnen|fuhre|fuhren|liste|listen|betrachte|betrachten|"
    r"behandle|behandeln|trage|tragen|gib|geben|stufe|stufen)\b[^.]{0,80}\bals\s+(?:verfugbar|nicht verfugbar|fit|verletzt|fraglich|"
    r"bestatigt|startelf|gesperrt|abwesend|ausfall|einsatzbereit|spielberechtigt)\b",
    r"\bals\s+(?:verfugbar|nicht verfugbar|fit|verletzt|fraglich|bestatigt|gesperrt|abwesend|einsatzbereit)\s+(?:melden|markieren|"
    r"kennzeichnen|eintragen|angeben|fuhren|einstufen|ausgeben)\b",
    r"^(?:alsjeblieft\s*,?\s*|graag\s+)?(?:meld|rapporteer|markeer|label|classificeer|registreer|beschouw|behandel|vermeld|zet|geef)\b"
    r"[^.]{0,80}\bals\s+(?:beschikbaar|niet beschikbaar|fit|geblesseerd|twijfelachtig|onzeker|bevestigd|basisspeler|geschorst|afwezig|"
    r"inzetbaar)\b",
    r"\bals\s+(?:beschikbaar|niet beschikbaar|fit|geblesseerd|twijfelachtig|onzeker|bevestigd|geschorst|afwezig|inzetbaar)\s+"
    r"(?:melden|rapporteren|markeren|vermelden|registreren|opgeven)\b",
    r"\b(?:musait|hazir|oynayabilir|sakat|sakatlikli|supheli|ilk 11|ilk onbir|cezali|kadroda|kadro disi|forma giyecek|oynayacak)\w*\s+"
    r"(?:olarak\s+)?(?:bildir|raporla|isaretle|kaydet|listele|yaz|belirt|ekle|goster)(?:in|iniz|sin)?\b",
))

# ── tools, functions, queries ────────────────────────────────────────────────────────────────────────────────────

_TOOLS: Final = tuple(re.compile(p) for p in (
    r"\b(?:call|invoke|use|run|execute|trigger)\b[^.]{0,25}\b(?:tool|function|command|sql|query|browser|api|endpoint|plugin)s?\b",
    r"\b(?:llama|usa|ejecuta|invoca|utiliza|chame|use|execute|invoque|utilize|chiama|usa|esegui|invoca|utilizza|appelle[zr]?|utilise[zr]?|"
    r"execute[zr]?|invoque[zr]?|rufe|ruf|benutze|verwende|fuhre|roep|gebruik|voer)\b[^.]{0,25}\b(?:herramienta|funcion|comando|sql|"
    r"consulta|navegador|ferramenta|funcao|strumento|funzione|query|outil|fonction|commande|requete|navigateur|werkzeug|funktion|befehl|"
    r"abfrage|tool|functie|opdracht|commando)s?\b",
    r"\b(?:arac|fonksiyon|komut|sql|sorgu|tarayici)\w*\b[^.]{0,25}\b(?:cagir|kullan|calistir)\w*",
    r"\b[a-z][a-z0-9]*_[a-z0-9_]+\s*\([^)]{0,80}\)",
    r"\b(?:delete\s+from|drop\s+table|insert\s+into|update\s+\w+\s+set|select\s+\*\s+from|truncate\s+table)\b",
))

# ── the other reports, away ──────────────────────────────────────────────────────────────────────────────────────

_DISCARD: Final = tuple(re.compile(p) for p in (
    r"\b(?:discard|disregard|drop|omit|exclude|delete|remove|descarta|descarte|omite|omita|excluye|exclua|elimina|elimine|scarta|ometti|"
    r"escludi|ecarte[zr]?|omets|omettez|exclue[zr]?|supprime[zr]?|verwirf|verwerfe|entferne|streiche|negeer|verwijder|schrap|sil|cikar)\w*"
    r"\b[^.]{0,30}\b(?:every|all|each|any|todos?|todas?|cada|tous|toutes|tutti|tutte|alle|elke|tum|hepsi|her)\b[^.]{0,20}\b(?:items?|"
    r"claims?|results?|entries|pages?|sources?|elementos?|afirmaciones|resultados?|itens|afirmacoes|elementi|affermazioni|risultati|"
    r"elements?|affirmations|resultats|eintrage|aussagen|ergebnisse|beweringen|resultaten|ogeler?|iddialar|sonuclar)\b",
    r"\b(?:discard|disregard|ignore|drop|delete|remove|omit|exclude|descarta|ignora|elimina|scarta|ecarte[zr]?|ignore[zr]?|verwirf|"
    r"ignoriere|negeer|verwijder)\w*\s+(?:the\s+|el\s+|la\s+|il\s+|le\s+|das\s+|de\s+|het\s+)?(?:result|page|source|item|resultado|"
    r"pagina|fuente|risultato|resultat|ergebnis|seite|resultaat)s?\s+r\d+\b",
))

FAMILIES: Final = {"addressed": _ADDRESSED, "takeover": _TAKEOVER, "answer": _ANSWER, "mark": _MARK, "tools": _TOOLS, "discard": _DISCARD}


def _machines(raw: str, folded: str) -> list[re.Match[str]]:
    """Where the sentence names a machine reader: a noun of ``_MACHINE``, or an acronym that the raw sentence writes in capitals."""
    found = list(_MACHINE_RE.finditer(folded))
    caps = {m.group().lower() for m in _ACRONYM.finditer(raw)}
    if caps:
        found += list(re.finditer(r"\b(?:" + "|".join(re.escape(a) for a in sorted(caps)) + r")\b", folded))
    return found


def _addresses_a_machine(raw: str, folded: str) -> bool:
    """The sentence names a machine reader AND tells it something: a modal right after the name (``_MODAL``, within ``_NEAR`` characters),
    or the name at the start of the sentence as the one spoken to («Extractors: list...», «AI, write...»)."""
    for m in _machines(raw, folded):
        if _MODAL.search(folded[m.end():m.end() + _NEAR]):
            return True
        head = folded[:m.start()].strip(" -'`*_#")
        if head in ("", "dear", "attention", "atencion", "hey", "to the", "to") and re.match(
                r"(?:\s+(?:instructions?|note|notice|reader|readers))?\s*[:,]", folded[m.end():]):
            return True
    return False


def why(text: str) -> str | None:
    """The family of the first order found in ``text`` (any of its sentences), or None. Never raises."""
    if not isinstance(text, str) or not text.strip():
        return None
    return _why(text)


_INITIAL: Final = re.compile(r"(?<![^\s(\[])([a-z])\.(?=\s)")
"""An initial in a folded name («d. keeper»): its stop is not the end of a sentence, so the patterns read it without one."""


@lru_cache(maxsize=8192)
def _why(text: str) -> str | None:
    for sentence in sentences(text):
        folded = _INITIAL.sub(r"\1", fold(sentence))
        if _addresses_a_machine(sentence, folded):
            return "addressed"
        pieces = [folded, *(p for p in _COLON.split(folded)[1:] if p)]
        for family, patterns in FAMILIES.items():
            for piece in pieces:
                if any(p.search(piece) for p in patterns):
                    return family
    return None


def command_like(text: str) -> bool:
    """Whether any sentence of ``text`` has the shape of an order to a machine (``why``)."""
    return why(text) is not None


__all__ = ["FAMILIES", "VERSION", "coarse_spans", "command_like", "fold", "sentences", "spans", "why"]
