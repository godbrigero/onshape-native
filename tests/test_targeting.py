import pytest

from onshape_native.client import OnshapeError
from onshape_native.targeting import resolve_context

URL = f"https://cad.onshape.com/documents/{'a'*24}/w/{'b'*24}/e/{'c'*24}"
OTHER = URL[:-24] + "d"*24


def context():
    return {"context_version": 1, "last_focused_window_id": 2, "tabs": [
        {"id": 11, "url": OTHER, "active": True, "window_id": 1},
        {"id": 12, "url": OTHER, "active": False, "window_id": 2},
        {"id": 13, "url": URL, "active": True, "window_id": 2}]}


def test_current_tab_uses_last_focused_window_not_first_active_tab():
    result = resolve_context(context=context())
    assert result["status"] == "resolved" and result["tab_id"] == 13
    assert result["url"] == URL and result["native_editor_eligible"]


def test_explicit_url_is_authoritative_and_works_offline():
    result = resolve_context(URL, context=context())
    assert result["source"] == "url" and result["tab_id"] is None
    reference = URL.replace("/w/", "/v/") + "?configuration=Length%3D12%20mm"
    result = resolve_context(reference)
    assert result["url"] == reference and result["target"]["configuration"] == "Length=12 mm"
    assert not result["workspace_url"] and not result["native_editor_eligible"]
    assert resolve_context(URL.rsplit("/e/", 1)[0])["target"]["eid"] is None


@pytest.mark.parametrize("mutate", [
    lambda c: c.pop("context_version"),
    lambda c: c.update(last_focused_window_id=None),
    lambda c: c.update(last_focused_window_id=3),
    lambda c: c["tabs"][2].update(active=False),
    lambda c: c["tabs"][1].update(active=True),
    lambda c: c["tabs"][2].update(url="https://cad.onshape.com/documents"),
])
def test_old_extension_missing_window_and_ambiguous_tabs_never_guess(mutate):
    c = context(); mutate(c)
    assert resolve_context(context=c)["status"] == "needs_selection"


def test_explicit_tab_and_url_must_agree():
    assert resolve_context(tab_id=11, context=context())["url"] == OTHER
    assert resolve_context(URL, 11, context())["status"] == "needs_selection"
    assert resolve_context(tab_id=999, context=context())["status"] == "needs_selection"
    with pytest.raises(OnshapeError): resolve_context(tab_id=True)
    with pytest.raises(OnshapeError): resolve_context("https://example.com/documents/a")


@pytest.mark.asyncio
async def test_mcp_url_resolution_does_not_require_a_browser(monkeypatch):
    from onshape_native import server
    import json
    monkeypatch.setattr(server, "svc", lambda: pytest.fail("URL resolution must remain local"))
    assert json.loads(await server.resolve_target(URL))["status"] == "resolved"
