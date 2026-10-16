"""One function per public API. Each returns records or a named error."""

import re
from html import unescape
from urllib.parse import quote

from biomeagent.http import HttpClient, HttpError

EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
ANNOTATIONS = (
    "https://www.ebi.ac.uk/europepmc/annotations_api/annotationsByArticleIds"
)
PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name"
VMH = "https://www.vmh.life/api/public/sparql"
TRIALS = "https://clinicaltrials.gov/api/v2/studies"
BACDIVE = "https://api.bacdive.dsmz.de"
NCBI = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OMNIPATH = "https://omnipathdb.org/interactions"

PAGE_SIZE = 5
EXCERPT_CAP = 1500
EDGE_CAP = 15
MENTION_CAP = 20
INTERACTION_CAP = 20
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .+\-]{0,80}$")
_TAG = re.compile(r"<[^>]+>")


def search_europepmc(query, http=None):
    http = http or HttpClient()

    def call():
        payload = http.get_json(
            EUROPEPMC,
            params={"query": query, "format": "json", "pageSize": PAGE_SIZE},
        )
        records = []
        for hit in (payload.get("resultList") or {}).get("result") or []:
            record = {
                "source": "europepmc",
                "id": str(hit.get("pmid") or hit.get("id") or ""),
                "name": hit.get("title") or "",
                "title": hit.get("title") or "",
                "excerpt": _clip(hit.get("abstractText") or ""),
            }
            if _open_access(hit) and hit.get("pmcid"):
                xml = http.get_text(
                    "https://www.ebi.ac.uk/europepmc/webservices/rest/"
                    f"{hit['pmcid']}/fullTextXML"
                )
                record["excerpt"] = _clip(_text_from_xml(xml))
            records.append(record)
        return _ok(records)

    return _guard(call)


def annotate_paper(pmid, http=None):
    http = http or HttpClient()

    def call():
        payload = http.get_json(
            ANNOTATIONS,
            params={"articleIds": f"MED:{pmid}", "format": "json"},
        )
        articles = payload if isinstance(payload, list) else payload.get("articles") or []
        records = []
        for article in articles:
            for note in article.get("annotations") or []:
                tag = (note.get("tags") or [{}])[0]
                uri = tag.get("uri") or ""
                records.append(
                    {
                        "source": "annotations",
                        "kind": "mention",
                        "id": uri.rstrip("/").rsplit("/", 1)[-1],
                        "name": note.get("exact") or tag.get("name") or "",
                    }
                )
                if len(records) >= MENTION_CAP:
                    return _ok(records)
        return _ok(records)

    return _guard(call)


def lookup_pubchem(name, http=None):
    http = http or HttpClient()

    def call():
        payload = http.get_json(
            f"{PUBCHEM}/{quote(name)}/property/Title,MolecularFormula/JSON"
        )
        rows = (payload.get("PropertyTable") or {}).get("Properties") or []
        records = []
        for row in rows[:1]:
            records.append(
                {
                    "source": "pubchem",
                    "kind": "metabolite",
                    "id": str(row.get("CID")),
                    "name": row.get("Title") or name,
                    "formula": row.get("MolecularFormula") or "",
                }
            )
        return _ok(records)

    return _guard(call)


def lookup_vmh(name, http=None):
    http = http or HttpClient()
    if not _NAME.match(name or "") or any(
        token in name.upper() for token in ("SELECT", "WHERE", "PREFIX")
    ):
        return _fail("lookup_vmh accepts a metabolite name, not a SPARQL query")

    def call():
        found = _bindings(
            http,
            """
            SELECT ?abbr ?name ?formula WHERE {
              ?met a vmh:Metabolite ;
                   vmh:abbreviation ?abbr ;
                   rdfs:label ?name .
              OPTIONAL { ?met vmh:chargedFormula ?formula }
              FILTER(LCASE(STR(?name)) = LCASE("%(name)s")
                  || LCASE(STR(?abbr)) = LCASE("%(name)s"))
            } LIMIT 1
            """
            % {"name": name},
        )
        if not found:
            return _ok([])
        row = found[0]
        abbr = row["abbr"]
        reactions = [
            item["abbr"]
            for item in _bindings(
                http,
                """
                SELECT ?abbr WHERE {
                  ?rxn a vmh:Reaction ;
                       vmh:abbreviation ?abbr ;
                       vmh:formula ?formula .
                  FILTER(CONTAINS(?formula, "%(abbr)s["))
                } LIMIT %(cap)s
                """
                % {"abbr": abbr, "cap": EDGE_CAP},
            )
            if item.get("abbr")
        ]
        microbes = [
            item["organism"]
            for item in _bindings(
                http,
                """
                SELECT ?organism WHERE {
                  ?met vmh:abbreviation "%(abbr)s" .
                  ?microbe a vmh:Microbe ;
                           ?link ?met ;
                           vmh:organism ?organism .
                } LIMIT %(cap)s
                """
                % {"abbr": abbr, "cap": EDGE_CAP},
            )
            if item.get("organism")
        ]
        return _ok(
            [
                {
                    "source": "vmh",
                    "kind": "metabolite",
                    "id": abbr,
                    "name": row.get("name") or name,
                    "formula": row.get("formula") or "",
                    "reactions": reactions,
                    "microbes": microbes,
                }
            ]
        )

    return _guard(call, vmh=True)


def search_trials(query, http=None):
    http = http or HttpClient()

    def call():
        payload = http.get_json(
            TRIALS, params={"query.term": query, "pageSize": PAGE_SIZE}
        )
        records = []
        for study in payload.get("studies") or []:
            protocol = study.get("protocolSection") or {}
            identity = protocol.get("identificationModule") or {}
            interventions = (
                (protocol.get("armsInterventionsModule") or {}).get("interventions")
                or []
            )
            text = " ".join(
                piece
                for item in interventions
                for piece in (item.get("name"), item.get("description"))
                if piece
            )
            adverse = (study.get("resultsSection") or {}).get("adverseEventsModule")
            if adverse:
                text = f"{text} Adverse events: {_clip(str(adverse), 400)}".strip()
            records.append(
                {
                    "source": "clinicaltrials",
                    "kind": "trial",
                    "id": identity.get("nctId") or "",
                    "name": identity.get("briefTitle") or "",
                    "title": identity.get("briefTitle") or "",
                    "excerpt": _clip(text),
                }
            )
        return _ok(records)

    return _guard(call)


def lookup_bacdive(query, http=None):
    http = http or HttpClient()

    def call():
        if any(character.isdigit() for character in query):
            listing = http.get_json(
                f"{BACDIVE}/v2/culturecollectionno/{quote(query)}"
            )
        else:
            parts = query.split()
            genus = quote(parts[0])
            species = quote(parts[1]) if len(parts) > 1 else ""
            path = f"{BACDIVE}/v2/taxon/{genus}"
            if species:
                path = f"{path}/{species}"
            listing = http.get_json(path)
        ids = listing.get("results") or []
        if isinstance(ids, dict):
            ids = list(ids)
        if not ids:
            return _ok([])
        strain_id = str(ids[0])
        payload = http.get_json(f"{BACDIVE}/v2/fetch/{strain_id}")
        strain = (payload.get("results") or {}).get(strain_id) or {}
        taxonomy = strain.get("Name and taxonomic classification") or {}
        links = strain.get("External links") or {}
        return _ok(
            [
                {
                    "source": "bacdive",
                    "kind": "organism",
                    "id": strain_id,
                    "name": taxonomy.get("species") or query,
                    "culture": links.get("culture collection no.") or "",
                }
            ]
        )

    return _guard(call)


def lookup_taxon(name, http=None):
    http = http or HttpClient()

    def call():
        import os

        params = {
            "db": "taxonomy",
            "term": name,
            "retmode": "json",
            "tool": "biomeagent",
        }
        if os.getenv("NCBI_EMAIL"):
            params["email"] = os.environ["NCBI_EMAIL"]
        if os.getenv("NCBI_API_KEY"):
            params["api_key"] = os.environ["NCBI_API_KEY"]
        found = http.get_json(f"{NCBI}/esearch.fcgi", params=params)
        ids = (found.get("esearchresult") or {}).get("idlist") or []
        if not ids:
            return _ok([])
        tax_id = str(ids[0])
        summary = http.get_json(
            f"{NCBI}/esummary.fcgi",
            params={**params, "id": tax_id, "term": None},
        )
        row = (summary.get("result") or {}).get(tax_id) or {}
        return _ok(
            [
                {
                    "source": "ncbi_taxonomy",
                    "kind": "organism",
                    "id": tax_id,
                    "name": row.get("scientificname") or name,
                    "rank": row.get("rank") or "",
                }
            ]
        )

    return _guard(call)


def lookup_omnipath(compound, protein="", http=None):
    http = http or HttpClient()

    def call():
        params = {
            "datasets": "small_molecule",
            "organisms": "9606",
            "sources": compound,
            "genesymbols": 1,
            "fields": "sources,references,type",
            "format": "json",
            "limit": INTERACTION_CAP,
        }
        if protein:
            params["targets"] = protein
        payload = http.get_json(OMNIPATH, params=params)
        rows = payload if isinstance(payload, list) else payload.get("records") or []
        records = []
        for row in rows:
            compound_id = str(row.get("source_genesymbol") or row.get("source") or "")
            protein_name = str(row.get("target_genesymbol") or "")
            if str(compound).isdigit() and compound_id != str(compound):
                continue
            if protein and protein_name.lower() != protein.lower():
                continue
            records.append(
                {
                    "source": "omnipath",
                    "kind": "interaction",
                    "id": str(row.get("source_genesymbol") or row.get("source") or compound),
                    "name": str(row.get("target_genesymbol") or ""),
                    "protein": str(row.get("target_genesymbol") or ""),
                    "databases": _split_list(row.get("sources")),
                    "pmids": _pmids(row.get("references")),
                }
            )
            if len(records) >= INTERACTION_CAP:
                break
        return _ok(records)

    return _guard(call)


def _bindings(http, query):
    payload = http.get_json(VMH, params={"query": " ".join(query.split())})
    rows = []
    for binding in (payload.get("results") or {}).get("bindings") or []:
        rows.append({key: value.get("value") for key, value in binding.items()})
    return rows


def _ok(records):
    return {"records": records, "error": None}


def _fail(message):
    return {"records": [], "error": message}


def _guard(call, vmh=False):
    try:
        return call()
    except HttpError as exc:
        message = exc.message
        if vmh and message == "hourly cap":
            message = "VMH hourly cap"
        return _fail(message)


def _open_access(hit):
    return str(hit.get("isOpenAccess") or "").upper() == "Y"


def _text_from_xml(xml):
    return unescape(_TAG.sub(" ", xml or ""))


def _clip(text, limit=EXCERPT_CAP):
    collapsed = " ".join((text or "").split())
    return collapsed[:limit]


def _split_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    return [part for part in str(value).split(";") if part]


def _pmids(value):
    found = []
    for part in _split_list(value):
        pmid = part.rsplit(":", 1)[-1]
        if pmid.isdigit() and pmid not in found:
            found.append(pmid)
    return found
