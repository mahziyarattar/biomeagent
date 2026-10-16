"""Live checks. Run with EVAL_LIVE=1. BacDive, annotations, and trials stay out."""

import os

import pytest

from biomeagent.sources import (
    lookup_omnipath,
    lookup_pubchem,
    lookup_taxon,
    lookup_vmh,
    search_europepmc,
)

pytestmark = pytest.mark.skipif(os.getenv("EVAL_LIVE") != "1", reason="set EVAL_LIVE=1")


def test_live_europepmc_returns_papers():
    result = search_europepmc("postbiotic AND heat-killed")
    assert result["error"] is None
    assert result["records"]
    assert result["records"][0]["source"] == "europepmc"
    assert result["records"][0]["id"]


def test_live_pubchem_butyrate():
    result = lookup_pubchem("butyrate")
    record = result["records"][0]
    assert record["id"] == "104775"
    assert record["formula"] == "C4H7O2-"


def test_live_vmh_butyrate():
    result = lookup_vmh("butyrate")
    record = result["records"][0]
    assert record["id"] == "but"
    assert record["formula"] == "C4H7O2"


def test_live_taxon_akkermansia():
    result = lookup_taxon("Akkermansia muciniphila")
    record = result["records"][0]
    assert record["id"] == "239935"
    assert record["rank"] == "species"


def test_live_omnipath_butyric_acid_cid():
    result = lookup_omnipath("264", protein="FFAR2")
    assert result["error"] is None
    proteins = {record["protein"] for record in result["records"]}
    assert "FFAR2" in proteins
    assert {record["id"] for record in result["records"]} == {"264"}
