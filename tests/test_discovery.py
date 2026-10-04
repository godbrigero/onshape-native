import pytest

from onshape_native.client import OnshapeError
from onshape_native.discovery import index


@pytest.mark.parametrize("task,expected", [
    ("create a new assembly tab", "createAssembly"),
    ("change the cube height", "feature"),
    ("round the edges", "feature_template"),
    ("move a Part Studio tab into a folder", "document_edit"),
    ("find document edit history", "getDocumentHistory"),
])
def test_task_retrieval_returns_ten_relevant_invocable_candidates(task, expected):
    result = index().search(task)
    assert len(result["matches"]) == 10
    assert expected in [r["name"] for r in result["matches"][:5]]
    assert all(r["invoke"]["tool"] and "evidence" in r for r in result["matches"])
    assert [r["score"] for r in result["matches"]] == sorted((r["score"] for r in result["matches"]), reverse=True)


def test_manual_paging_exhausts_catalog_without_dropping_entries():
    names = []; offset = 0
    while True:
        page = index().browse(source="rest", offset=offset, limit=37)
        names += [r["name"] for r in page["matches"]]
        if page["next_offset"] is None: break
        offset = page["next_offset"]
    assert len(names) == len(set(names)) == 302
    result = index().browse(query="delete", source="rest", method="DELETE")
    assert result["matches"] and all(r["method"] == "DELETE" for r in result["matches"])


def test_exact_identity_and_unknown_query_and_read_only_filter():
    assert index().search("getDocumentContents")["matches"][0]["name"] == "getDocumentContents"
    assert index().search("zxqvplkjhunknown")["matches"] == []
    assert all(r["read_only"] for r in index().search("mass properties", read_only=True)["matches"])
    native = index().browse(source="native", query="GBTUiEditElementGroups")["matches"][0]
    assert "replay_verified" in native
    assert not index().browse(query="rest:session")["matches"][0]["available"]
    with pytest.raises(OnshapeError): index().search("", 10)
    with pytest.raises(OnshapeError): index().browse(offset=-1)
