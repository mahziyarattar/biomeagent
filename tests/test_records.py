import json
from urllib.parse import urlencode

from biomeagent.assemble import NO_SOURCE, assemble
from biomeagent.sources import (
    annotate_paper,
    lookup_bacdive,
    lookup_omnipath,
    lookup_pubchem,
    lookup_taxon,
    lookup_vmh,
    search_europepmc,
    search_trials,
)


def _vmh_butyrate():
    return {
        "head": {"vars": ["abbr", "name", "formula"]},
        "results": {
            "bindings": [
                {
                    "abbr": {"value": "but"},
                    "name": {"value": "Butyrate"},
                    "formula": {"value": "C4H7O2"},
                }
            ]
        },
    }


def _vmh_empty():
    return {"head": {"vars": []}, "results": {"bindings": []}}


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    def get_json(self, url, params=None):
        return self._body(url, params)

    def get_text(self, url, params=None):
        return self._body(url, params)

    def _body(self, url, params):
        recorded = url if not params else f"{url}?{urlencode(params)}"
        self.urls.append(recorded)
        hits = [key for key in self.routes if key in recorded]
        if not hits:
            raise AssertionError(f"unexpected url {recorded}")
        body = self.routes[max(hits, key=len)]
        if isinstance(body, Exception):
            raise body
        return body


def test_europepmc_fixture_copies_pmid():
    http = FakeHttp(
        {
            "/search": {
                "resultList": {
                    "result": [
                        {
                            "pmid": "35767074",
                            "title": "Postbiotic heat-killed lactobacilli",
                            "abstractText": "A pig model.",
                            "isOpenAccess": "N",
                        }
                    ]
                }
            }
        }
    )
    result = search_europepmc("postbiotic AND heat-killed", http=http)
    assert result["error"] is None
    assert result["records"][0]["source"] == "europepmc"
    assert result["records"][0]["id"] == "35767074"
    assert result["records"][0]["title"] == "Postbiotic heat-killed lactobacilli"
    assert not any("fullTextXML" in url for url in http.urls)


def test_open_access_fetches_excerpt_and_closed_does_not():
    http = FakeHttp(
        {
            "/search": {
                "resultList": {
                    "result": [
                        {
                            "pmid": "35767074",
                            "title": "Open paper",
                            "abstractText": "Abstract.",
                            "isOpenAccess": "Y",
                            "pmcid": "PMC9243212",
                        }
                    ]
                }
            },
            "fullTextXML": "<article><p>" + ("word " * 800) + "</p></article>",
        }
    )
    result = search_europepmc("postbiotic", http=http)
    assert any("PMC9243212/fullTextXML" in url for url in http.urls)
    assert len(result["records"][0]["excerpt"]) <= 1500
    assert "word" in result["records"][0]["excerpt"]


def test_annotation_mention_keeps_taxonomy_1578():
    http = FakeHttp(
        {
            "annotationsByArticleIds": [
                {
                    "extId": "35767074",
                    "annotations": [
                        {
                            "exact": "lactobacilli",
                            "type": "Organisms",
                            "tags": [
                                {
                                    "name": "paralactobacillus",
                                    "uri": "http://identifiers.org/taxonomy/1578",
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    result = annotate_paper("35767074", http=http)
    record = result["records"][0]
    assert record["source"] == "annotations"
    assert record["kind"] == "mention"
    assert record["id"] == "1578"
    assert record["name"] == "lactobacilli"


def test_pubchem_and_vmh_keep_distinct_formulas():
    http = FakeHttp(
        {
            "pubchem": {
                "PropertyTable": {
                    "Properties": [
                        {
                            "CID": 104775,
                            "Title": "Butyrate",
                            "MolecularFormula": "C4H7O2-",
                        }
                    ]
                }
            },
            "chargedFormula": _vmh_butyrate(),
            "Reaction": _vmh_empty(),
            "Microbe": _vmh_empty(),
        }
    )
    chemical = lookup_pubchem("butyrate", http=http)
    model = lookup_vmh("butyrate", http=http)
    assert chemical["records"][0]["id"] == "104775"
    assert chemical["records"][0]["formula"] == "C4H7O2-"
    assert model["records"][0]["id"] == "but"
    assert model["records"][0]["formula"] == "C4H7O2"
    assert model["records"][0]["reactions"] == []
    assert model["records"][0]["microbes"] == []


def test_vmh_rejects_sparql_from_the_agent():
    http = FakeHttp({"sparql": {}})
    result = lookup_vmh("SELECT * WHERE { ?s ?p ?o }", http=http)
    assert result["records"] == []
    assert result["error"]
    assert http.urls == []


def test_trial_record_uses_nct_id():
    http = FakeHttp(
        {
            "clinicaltrials.gov": {
                "studies": [
                    {
                        "protocolSection": {
                            "identificationModule": {
                                "nctId": "NCT07268846",
                                "briefTitle": "Tributyrin before surgery",
                            },
                            "armsInterventionsModule": {
                                "interventions": [
                                    {"description": "Tributyrin 900 mg/day for 7 days"}
                                ]
                            },
                        }
                    }
                ]
            }
        }
    )
    result = search_trials("postbiotic", http=http)
    record = result["records"][0]
    assert record["source"] == "clinicaltrials"
    assert record["kind"] == "trial"
    assert record["id"] == "NCT07268846"
    assert "900 mg/day" in record["excerpt"]


def test_taxon_rank():
    http = FakeHttp(
        {
            "esearch": {"esearchresult": {"idlist": ["239935"]}},
            "esummary": {
                "result": {
                    "239935": {
                        "scientificname": "Akkermansia muciniphila",
                        "rank": "species",
                    }
                }
            },
        }
    )
    result = lookup_taxon("Akkermansia muciniphila", http=http)
    record = result["records"][0]
    assert record["source"] == "ncbi_taxonomy"
    assert record["kind"] == "organism"
    assert record["id"] == "239935"
    assert record["rank"] == "species"


def test_bacdive_sample_and_timeout_beside_pubchem():
    http = FakeHttp(
        {
            "/v2/taxon/": {"results": [24493]},
            "/v2/fetch/": {
                "results": {
                    "24493": {
                        "Name and taxonomic classification": {
                            "species": "Akkermansia muciniphila"
                        },
                        "External links": {"culture collection no.": "DSM 22959"},
                    }
                }
            },
        }
    )
    strain = lookup_bacdive("Akkermansia muciniphila", http=http)
    assert strain["records"][0]["source"] == "bacdive"
    assert strain["records"][0]["id"] == "24493"
    assert strain["records"][0]["culture"] == "DSM 22959"

    failed = {"records": [], "error": "timed out"}
    chemical = lookup_pubchem(
        "butyrate",
        http=FakeHttp(
            {
                "pubchem": {
                    "PropertyTable": {
                        "Properties": [
                            {
                                "CID": 104775,
                                "Title": "Butyrate",
                                "MolecularFormula": "C4H7O2-",
                            }
                        ]
                    }
                }
            }
        ),
    )
    response = assemble(
        [
            {"role": "assistant", "content": "Here is the chemical."},
            {"role": "tool", "name": "lookup_bacdive", "content": json.dumps(failed)},
            {
                "role": "tool",
                "name": "lookup_pubchem",
                "content": json.dumps(chemical),
            },
        ]
    )
    assert [record["source"] for record in response["records"]] == ["pubchem"]
    assert response["errors"] == [{"tool": "lookup_bacdive", "message": "timed out"}]


def test_omnipath_interaction_keeps_compound_id():
    http = FakeHttp(
        {
            "omnipathdb.org": [
                {
                    "source_genesymbol": "30768",
                    "target_genesymbol": "FFAR2",
                    "sources": ["SIGNOR"],
                    "references": "SIGNOR:31160049",
                },
                {
                    "source_genesymbol": "264",
                    "target_genesymbol": "FFAR3",
                    "sources": "Cellinker",
                    "references": "Cellinker:12711604",
                },
                {
                    "source_genesymbol": "264",
                    "target_genesymbol": "FFAR2",
                    "sources": "Cellinker;Guide2Pharma_Cellinker",
                    "references": "Cellinker:21220428;Cellinker:12684041",
                },
            ]
        }
    )
    result = lookup_omnipath("264", protein="FFAR2", http=http)
    record = result["records"][0]
    assert record["source"] == "omnipath"
    assert record["kind"] == "interaction"
    assert record["id"] == "264"
    assert record["protein"] == "FFAR2"
    assert "21220428" in record["pmids"]
    assert "Guide2Pharma_Cellinker" in record["databases"]
    assert "sources=264" in http.urls[0]
    assert "targets=FFAR2" in http.urls[0]


def test_empty_tool_result_is_not_an_error():
    response = assemble(
        [
            {"role": "assistant", "content": "Nothing matched."},
            {
                "role": "tool",
                "name": "search_trials",
                "content": json.dumps({"records": [], "error": None}),
            },
        ]
    )
    assert response["records"] == []
    assert response["errors"] == []
    assert response["reply"] == "Nothing matched."
    assert response["calls"] == [{"tool": "search_trials", "records": [], "error": None}]


def test_two_calls_to_the_same_source_stay_apart():
    response = assemble(
        [
            {
                "role": "tool",
                "name": "search_europepmc",
                "content": json.dumps({"records": [{"id": "1"}], "error": None}),
            },
            {
                "role": "tool",
                "name": "search_europepmc",
                "content": json.dumps({"records": [{"id": "2"}], "error": None}),
            },
            {
                "role": "tool",
                "name": "lookup_pubchem",
                "content": json.dumps({"records": [], "error": "timed out"}),
            },
        ]
    )
    assert [call["tool"] for call in response["calls"]] == [
        "search_europepmc",
        "search_europepmc",
        "lookup_pubchem",
    ]
    assert response["calls"][0]["records"] == [{"id": "1"}]
    assert response["calls"][1]["records"] == [{"id": "2"}]
    assert response["calls"][2]["error"] == "timed out"
    assert [record["id"] for record in response["records"]] == ["1", "2"]


def test_no_tool_call_keeps_the_reply_and_failures_do_not():
    greeting = assemble([{"role": "assistant", "content": "I am BiomeAgent."}])
    failed = assemble(
        [
            {"role": "assistant", "content": "I found a paper."},
            {
                "role": "tool",
                "name": "lookup_pubchem",
                "content": json.dumps({"records": [], "error": "HTTP 500"}),
            },
        ]
    )
    assert greeting["reply"] == "I am BiomeAgent."
    assert greeting["records"] == []
    assert greeting["errors"] == []
    assert failed["reply"] == NO_SOURCE
    assert failed["records"] == []
    assert failed["errors"][0]["tool"] == "lookup_pubchem"


def test_identifiers_come_from_the_trace_only():
    response = assemble(
        [
            {
                "role": "assistant",
                "content": "See NCT99999999 and CID 1.",
            },
            {
                "role": "tool",
                "name": "lookup_pubchem",
                "content": json.dumps(
                    {
                        "records": [
                            {
                                "source": "pubchem",
                                "id": "104775",
                                "name": "Butyrate",
                                "formula": "C4H7O2-",
                            }
                        ],
                        "error": None,
                    }
                ),
            },
        ]
    )
    assert [record["id"] for record in response["records"]] == ["104775"]


def test_scripted_butyrate_turn_shape():
    http = FakeHttp(
        {
            "pubchem": {
                "PropertyTable": {
                    "Properties": [
                        {
                            "CID": 104775,
                            "Title": "Butyrate",
                            "MolecularFormula": "C4H7O2-",
                        }
                    ]
                }
            },
            "chargedFormula": _vmh_butyrate(),
            "Reaction": _vmh_empty(),
            "Microbe": _vmh_empty(),
        }
    )
    response = assemble(
        [
            {"role": "assistant", "content": "Butyrate is a chemical in both sources."},
            {
                "role": "tool",
                "name": "lookup_pubchem",
                "content": json.dumps(lookup_pubchem("butyrate", http=http)),
            },
            {
                "role": "tool",
                "name": "lookup_vmh",
                "content": json.dumps(lookup_vmh("butyrate", http=http)),
            },
        ]
    )
    assert set(response) == {"reply", "records", "errors", "calls"}
    assert [call["tool"] for call in response["calls"]] == ["lookup_pubchem", "lookup_vmh"]
    assert response["calls"][0]["records"][0]["formula"] == "C4H7O2-"
    assert response["calls"][1]["error"] is None
    assert response["errors"] == []
    by_source = {record["source"]: record for record in response["records"]}
    assert by_source["pubchem"]["formula"] == "C4H7O2-"
    assert by_source["vmh"]["formula"] == "C4H7O2"
    assert by_source["vmh"]["id"] == "but"
