# BiomeAgent — design draft

This folder is the project root. Git has not been initialized.

BiomeAgent is a thesis assistant. A person asks in ordinary language. A ReAct agent calls free public APIs and answers from the records those APIs return. The reply text is the model's. Identifiers in the structured result are copied in Python from the tool trace of that same request.

Version 1 is the live APIs only. MiMeDB is a download, not a live API, and needs a local search index. That index is a later version, not version 1.

## What a person can ask

The assistant can answer when the fact is already in a paper, a text-mined mention, a chemical record, a metabolic-model entry, a registered trial, a strain sheet, or a taxonomy record.

- What butyrate is, and that it is a chemical. PubChem returns CID `104775`, title Butyrate, formula `C4H7O2-`. VMH returns the same metabolite with abbreviation `but` when the fixed query hits.
- Which papers discuss a heat-killed postbiotic. Europe PMC search `postbiotic AND heat-killed` returned 631 hits, including PMID `35767074` and PMID `37279829`.
- Which genes, chemicals, diseases, or organisms a paper mentions. The annotations call on PMID `35767074` returned `lactobacilli` linked to NCBI taxonomy `1578`. Those are mentions in the text, not curated cause-and-effect links.
- Which registered trials use the word postbiotic. Examples already returned: `NCT07268846`, `NCT07602426`, `NCT07471659`.
- The official name and rank of an organism. `Akkermansia muciniphila` is taxonomy id `239935`, rank species.

The assistant cannot answer these, including by calling every tool in one turn:

- Inactivation temperature, duration, or a structured daily dose, unless that string is already in the abstract, the open-access full text, or the trial's intervention text.
- Whether a commercial strain code meets the ISAPP definition. Codes such as MIMBb75 are not taxonomy ids, and BacDive does not store "health benefit after inactivation."
- Which butyrate-producing microbes were inside a named commercial product. A chemical record, a trial title, and a taxonomy record do not identify the contents of that product. A killed cell does not keep producing metabolites the way a live culture does.
- A personal dose or a medical instruction.
- A new postbiotic design, or a ranked list of preparations by efficacy.
- Which host gene a metabolite regulates, as a curated edge. Version 1 has text-mined mentions and VMH's fixed metabolite query. It does not have gutMGene, and it does not have the MiMeDB microbe–metabolite table yet.

Two kinds stay labeled. A postbiotic, in the ISAPP sense, is a preparation of inanimate microorganisms and/or their components that confers a health benefit. A metabolite is a chemical a microbe makes. Both kinds may appear in an answer. A row that is only a chemical is labeled `metabolite`. The words for a heat-killed cell and for a metabolite stay apart in the reply. This version does not set a `preparation` label on records. The model does not collapse the two.

A short picture of the difference: live organisms in doogh are a probiotic; the same organisms after killing are a preparation; lactic acid separated from the doogh is a metabolite.

## Version 1 shape

```text
Streamlit UI
    |  POST /chat  (message list)
FastAPI
    |  LangGraph ReAct agent (OpenRouter)
    |-- search_europepmc     Europe PMC
    |-- annotate_paper       Europe PMC Annotations
    |-- lookup_pubchem       PubChem
    |-- lookup_vmh           VMH SPARQL, fixed queries only
    |-- search_trials        ClinicalTrials.gov
    |-- lookup_bacdive       BacDive v2
    |-- lookup_taxon         NCBI Taxonomy
    |-- lookup_omnipath     OmniPath small-molecule interactions
    |
    tool trace -> Python copy of records -> JSON response
```

Streamlit is the only interface. It keeps the chat history in `st.session_state` and sends that history with each request. FastAPI is stateless in version 1. There is no cookie session and no React app.

The agent chooses tools. It does not call all seven on every question. The system prompt tells it:

- keep `preparation` and `metabolite` as different labels
- treat annotations as mentions
- not to send the bare word `heat-killed` to ClinicalTrials.gov, because that query also matches vaccines
- not to invent an identifier that no tool returned

`lookup_vmh` accepts a metabolite name and runs a small set of fixed SPARQL queries. The agent does not write SPARQL. VMH allows about 100 requests an hour and needs no key. The verified query returns Butyrate, abbreviation `but`, formula `C4H7O2`. If a fixed query returns no microbe or reaction edge, that list is empty.

`search_europepmc` returns PMID, title, and abstract. When the record is open access, the same tool also fetches the full-text XML. Closed articles stay at the abstract.

`search_trials` requests the intervention text and, when the registry has posted results, the adverse-event fields on that same study. It does not call openFDA.

`lookup_bacdive` looks up a genus and species, or a culture-collection number, and returns taxonomy, culture, and physiology for the living strain. From this development network the BacDive host has timed out. The tool still exists. A timeout omits the strain block.

`lookup_taxon` uses NCBI E-utilities. An API key is optional and raises the rate limit. The key is not required for version 1.

## Later, not version 1

MiMeDB is the microbial metabolome database. Its compound and microbe tables are CSV downloads under CC BY-NC. There is no public self-serve REST API. Loading those CSV files into a local Elasticsearch index, and exposing `search_mimedb`, waits until the live assistant works. Genes, genomes, and spectra from MiMeDB are out even then. The Elasticsearch instance would be local to BiomeAgent, not a shared cluster.

Also later, and not promised: Reactome (the search calls tried here failed), StrainInfo and LPSN (same DSMZ host as BacDive, or a free account), openFDA food recalls, MetGENE (KEGG license), gutMGene, gutMDisorder, and GMMAD2 (no usable public REST found).

## Response

`POST /chat` accepts the message list and returns:

- `reply`: the model's prose
- `records`: one list, each item tagged with `source` (`europepmc`, `annotations`, `pubchem`, `vmh`, `clinicaltrials`, `bacdive`, `ncbi_taxonomy`, `omnipath`) and a `kind` where the source supports it (`metabolite`, `organism`, `trial`, `mention`, `interaction`)
- `errors`: tools that failed on this turn, by name, with no stack trace

The Python layer walks the tool trace and copies records from tool return values. A PMID, CID, NCT id, or taxonomy id appears in `records` only if a tool returned it on this turn.

## When a source fails

Each tool catches its own failure. The other tools' records stay in the response. An empty result is a successful call with zero records. A timeout, an HTTP error, and VMH's hourly cap are failures: that tool is named in `errors` and contributes no records. If every tool fails, `records` is empty and the reply says that no source returned anything.

## Tests

Default tests use saved JSON and do not touch the network.

| Fixture | Produces |
| --- | --- |
| Europe PMC search | PMID `35767074`, source `europepmc` |
| Annotations for that PMID | organism mention `lactobacilli`, taxonomy `1578`, kind `mention` |
| PubChem `butyrate` | CID `104775`, formula `C4H7O2-` |
| VMH `butyrate` | abbreviation `but`; missing edges stay an empty list |
| Trials `postbiotic` | NCT `NCT07268846` |
| NCBI `Akkermansia muciniphila` | taxonomy id `239935`, rank species |
| BacDive sample | taxonomy and culture, source `bacdive` |

Trace tests:

- BacDive timeout plus a successful PubChem call leaves the chemical and omits the strain.
- An empty list adds no record and is not an error.
- All tools failing yields an empty `records` list and a reply that no source returned.
- Identifiers in `records` are copied from the trace.
- `lookup_vmh` rejects a raw SPARQL string from the agent.
- Full text is requested only when the Europe PMC fixture is marked open access.

The language model is not run in these tests. One scripted turn calls PubChem and VMH for a butyrate question and checks the response shape.

`EVAL_LIVE=1` runs the known queries once against Europe PMC, PubChem, NCBI Taxonomy, and VMH. BacDive is not in that live set. Elasticsearch is not started.

## Stack

- Python 3.11+
- FastAPI for the agent service
- LangGraph ReAct agent
- OpenRouter for the model, same pattern as ProtDAP (`OPENROUTER_API_KEY`, `OPENROUTER_MODEL`)
- Streamlit for the interface
- HTTP client for the seven APIs
- pytest for the fixture tests

No Node service, no React app, no Elasticsearch, and no MiMeDB files in version 1.

## Run, once implemented

```text
uvicorn biomeagent.main:app --reload
streamlit run streamlit_app.py
```

The Streamlit app reads `BIOMEAGENT_API_URL`, default `http://127.0.0.1:8000`.

## License note

The live APIs are public. VMH is used within its published rate limit. MiMeDB, when a later version loads it, is CC BY-NC and is for a non-commercial thesis. That limit will be stated again next to the loader.

## Initial build

`lookup_omnipath` takes `compound` (a name or a PubChem CID, as the agent wrote it) and an optional `protein`. It sends one fixed small-molecule request. A row is `source=omnipath` and `kind=interaction`: compound id, protein symbol, upstream database names, and PubMed ids. CID `104775` is not rewritten as CID `264`.

Python sets `kind` from the tool return. This version does not set `preparation`. The system prompt still keeps a preparation and a metabolite apart. Fixture tests do not assert `preparation` or `metabolite`.

A turn where every tool fails returns an empty `records` list and the reply `No source returned anything.` A turn with no tool call keeps the model's reply and an empty `records` list. On every other turn the model writes the reply. An empty tool result is a success. A dose or duration may be quoted only when that string is already in an abstract, open-access full text, or intervention text. A personal dose or a medical instruction stays out.

Europe PMC returns at most 5 hits. An open-access full text is clipped to 1,500 characters. `lookup_vmh` runs three fixed queries (metabolite, reactions, microbes) against `https://www.vmh.life/api/public/sparql` and rejects a SPARQL string. ClinicalTrials.gov is API v2. NCBI sends tool name `biomeagent` and `NCBI_EMAIL` when that variable is set. The agent stops after 8 steps. Each HTTP call times out at 20 seconds.

`EVAL_LIVE=1` calls Europe PMC, PubChem, NCBI Taxonomy, VMH, and OmniPath. Annotations, ClinicalTrials.gov, and BacDive stay out of that live set. `OPENROUTER_MODEL` must be a model that can call tools. Streamlit shows `reply`, `records`, and `errors`.
