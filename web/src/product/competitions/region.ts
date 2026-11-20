/**
 * The region of a competition for the directory (lámina I08), from its country's ISO code: the football confederation the country
 * plays in (Kazakhstan and Israel in Europe, Australia in Asia, Guyana and Suriname in the north). International competitions (no
 * country, «World») go to «Torneos internacionales». A country this list does not know goes to «Otras» rather than being guessed.
 */
export const REGIONS = [
  "sudamerica",
  "europa",
  "norte",
  "asia",
  "africa",
  "internacional",
  "otras",
] as const;
export type Region = (typeof REGIONS)[number];

const BY_REGION: Record<Exclude<Region, "europa" | "internacional" | "otras">, string> = {
  sudamerica: "AR BO BR CL CO EC PY PE UY VE",
  norte:
    "US CA MX GT SV HN NI CR PA BZ JM TT HT DO CU PR BB BS AG DM GD KN LC VC SR GY GF BM KY VG VI AW CW SX BQ MQ GP MS TC AI",
  asia: "AF AU BH BD BT BN KH CN TW GU HK IN ID IR IQ JP JO KP KR KW KG LA LB MO MY MV MN MM NP OM PK PS PH QA SA SG LK SY TJ TH TL TM AE UZ VN YE NZ FJ PG SB VU NC TO WS TV CK AS PF",
  africa:
    "DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU MA MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW RE YT",
};

const EUROPE =
  "AL AD AM AT AZ BY BE BA BG HR CY CZ DK EE FO FI FR GE DE GI GR HU IS IE IL IT KZ XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH TR UA GB";

const REGION_OF = new Map<string, Region>();
for (const [region, codes] of Object.entries(BY_REGION))
  for (const code of codes.split(" ")) REGION_OF.set(code, region as Region);
for (const code of EUROPE.split(" ")) REGION_OF.set(code, "europa");

/** «CO» -> sudamerica, «GB-ENG» -> europa; no country or «World» -> internacional. */
export function regionOf(
  country: string | null | undefined,
  code: string | null | undefined,
): Region {
  const name = (country ?? "").trim().toLowerCase();
  if (!name || name === "world") return "internacional";
  const iso = (code ?? "").trim().toUpperCase();
  if (!iso) return "otras";
  return REGION_OF.get(iso.startsWith("GB-") ? "GB" : iso) ?? "otras";
}
