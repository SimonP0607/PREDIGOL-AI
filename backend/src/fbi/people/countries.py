"""Which words are the name of a country: the one list the identity of people is read with (plan F3).

The provider writes a referee as ``Name, Country`` (``Michael Oliver, England``) or, for part of its history, surname first
(``Brooks, John, England``), and a competition's country as ``Czech-Republic``. To tell a country from a given name
("Georgia" is both) and to compare ``Türkiye`` with ``Turkey`` there has to be one list; this is it.

A country has one KEY (its lower-case, accent-free name with spaces, ``czech republic``) and any number of spellings that
lead to it. Nothing here is a model of the world: it is the set of names that appeared in the provider's referee and
competition fields, plus the rest of the football associations, so that an unlisted word is read as a given name, never
as a country.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

UNKNOWN_SCOPE: Final = "?"
"""The scope of an observation that says no country and sits in a competition that belongs to none (a continental cup)."""

_LETTERS = str.maketrans({"ß": "ss", "ø": "o", "đ": "d", "ł": "l", "æ": "ae", "œ": "oe", "ð": "d", "þ": "th", "\u0131": "i"})
_APOSTROPHES = re.compile("['`\u00b4\u2019\u2018\u02bc]")  # apostrophes, acute accent, curly quotes, modifier letter
_NON_WORD = re.compile(r"[^a-z0-9]+")


def plain(text: object) -> str:
    """Lower case, no accents, no punctuation, one space between words: 'Türkiye' -> 'turkiye', "Côte d'Ivoire" ->
    'cote divoire'. An apostrophe disappears without leaving a gap, so "D'Amico" is not read as an initial and a surname."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().translate(_LETTERS)
    s = _APOSTROPHES.sub("", s)
    return " ".join(_NON_WORD.sub(" ", s).split())


# canonical name | other spellings, one country a line. The canonical name is the key's display form.
_COUNTRIES: Final = """
Afghanistan
Albania
Algeria
American Samoa
Andorra
Angola
Anguilla
Antigua and Barbuda|Antigua And Barbuda|Antigua-And-Barbuda
Argentina
Armenia
Aruba
Australia
Austria
Azerbaijan
Bahamas
Bahrain
Bangladesh
Barbados
Belarus
Belgium
Belize
Benin
Bermuda
Bhutan
Bolivia
Bonaire
Bosnia and Herzegovina|Bosnia|Bosnia-Herzegovina|Bosnia & Herzegovina|Bosnia Herzegovina|Bosnia and Herz
Botswana
Brazil
British Virgin Islands
Brunei|Brunei Darussalam
Bulgaria
Burkina Faso
Burundi
Cambodia
Cameroon
Canada
Cape Verde|Cabo Verde|Cape Verde Islands
Cayman Islands
Central African Republic|Central African Rep
Chad
Chile
China|China PR|PR China
Chinese Taipei|Taiwan
Colombia
Comoros
Congo|Congo Republic|Republic of the Congo|Congo-Brazzaville
Cook Islands
Costa Rica
Croatia
Cuba
Curacao|Curaçao
Cyprus
Czech Republic|Czechia|Czech-Republic
Denmark
DR Congo|Congo DR|Congo-DR|Democratic Republic of the Congo|DR-Congo|Zaire
Djibouti
Dominica
Dominican Republic|Dominican-Republic
Ecuador
Egypt
El Salvador|El-Salvador
England
Equatorial Guinea
Eritrea
Estonia
Eswatini|Swaziland
Ethiopia
Faroe Islands|Faroe-Islands|Faroes
Fiji
Finland
France
French Guiana
Gabon
Gambia|The Gambia
Georgia
Germany
Ghana
Gibraltar
Greece
Grenada
Guadeloupe
Guam
Guatemala
Guinea
Guinea-Bissau|Guinea Bissau
Guyana
Haiti
Honduras
Hong Kong|Hong-Kong
Hungary
Iceland
India
Indonesia
Iran|IR Iran
Iraq
Ireland|Republic of Ireland|Rep of Ireland|Eire
Israel
Italy
Ivory Coast|Cote d'Ivoire|Côte d'Ivoire|Ivory-Coast
Jamaica
Japan
Jordan
Kazakhstan
Kenya
Kosovo
Kuwait
Kyrgyzstan|Kyrgyz Republic
Laos|Lao
Latvia
Lebanon
Lesotho
Liberia
Libya
Liechtenstein
Lithuania
Luxembourg
Macau|Macao
Madagascar
Malawi
Malaysia
Maldives
Mali
Malta
Martinique
Mauritania
Mauritius
Mexico
Moldova|Republic of Moldova
Monaco
Mongolia
Montenegro
Montserrat
Morocco
Mozambique
Myanmar|Burma
Namibia
Nepal
Netherlands|Holland|The Netherlands
New Caledonia
New Zealand|New-Zealand
Nicaragua
Niger
Nigeria
North Korea|Korea DPR|DPR Korea
North Macedonia|Macedonia|FYR Macedonia|FYROM
Northern Ireland|Northern-Ireland
Norway
Oman
Pakistan
Palestine
Panama
Papua New Guinea
Paraguay
Peru
Philippines
Poland
Portugal
Puerto Rico
Qatar
Reunion|Réunion
Romania
Russia|Russian Federation
Rwanda
Saint Kitts and Nevis|St Kitts and Nevis|Saint-Kitts-and-Nevis
Saint Lucia|St Lucia
Saint Vincent and the Grenadines|St Vincent and the Grenadines
Samoa
San Marino|San-Marino
Sao Tome and Principe
Saudi Arabia|Saudi-Arabia
Scotland
Senegal
Serbia
Seychelles
Sierra Leone
Singapore
Sint Maarten
Slovakia
Slovenia
Solomon Islands
Somalia
South Africa|South-Africa
South Korea|Korea Republic|Republic of Korea|Korea|South-Korea
South Sudan
Spain
Sri Lanka
Sudan
Suriname
Sweden
Switzerland
Syria
Tahiti
Tajikistan
Tanzania
Thailand
Timor-Leste|East Timor|Timor Leste
Togo
Tonga
Trinidad and Tobago|Trinidad-And-Tobago|Trinidad & Tobago
Tunisia
Turkey|Türkiye|Turkiye
Turkmenistan
Turks and Caicos Islands
USA|United States|United States of America|US
Uganda
Ukraine
United Arab Emirates|UAE|United-Arab-Emirates
Uruguay
US Virgin Islands
Uzbekistan
Vanuatu
Venezuela
Vietnam|Viet Nam
Wales
Yemen
Zambia
Zimbabwe
"""


def _build() -> tuple[dict[str, str], dict[str, str]]:
    by_alias: dict[str, str] = {}
    display: dict[str, str] = {}
    for line in _COUNTRIES.strip().splitlines():
        names = [n.strip() for n in line.split("|") if n.strip()]
        key = plain(names[0])
        display[key] = names[0]
        for name in names:
            by_alias[plain(name)] = key
    return by_alias, display


_BY_ALIAS, _DISPLAY = _build()


def country_key(text: object) -> str | None:
    """The key of the country a text names (``Türkiye`` and ``Turkey`` -> ``turkey``), None when it names none of them."""
    k = plain(text)
    return _BY_ALIAS.get(k) if k else None


def country_name(key: str | None) -> str | None:
    """The name a key is shown with ('czech republic' -> 'Czech Republic'); None for no key or the unknown scope."""
    return _DISPLAY.get(key) if key else None


def scope_of(country_text: object, competition_country: object, competition_type: str | None) -> str:
    """Where a referee comes from, as far as one observation says.

    The country the provider wrote next to the name, when it wrote one. Otherwise the country of a DOMESTIC competition
    (a league or a cup is refereed by its own country's referees in nine matches out of ten; the exceptions are the visiting
    referees, whom the identity rules find by other means). A continental or international competition says nothing:
    ``?``. A country the list does not know still makes a scope (its plain name), so two spellings of it agree with each
    other even when this list has not heard of it.
    """
    own = country_key(country_text)
    if own:
        return own
    if competition_type in ("domestic_league", "domestic_cup"):
        home = country_key(competition_country) or plain(competition_country)
        if home and home != "world":
            return home
    return UNKNOWN_SCOPE
