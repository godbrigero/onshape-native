// Report only Onshape tabs; no global tabs permission or other-site URL access.
export async function tabContext(browser) {
  const tabs = await browser.tabs.query({url: "https://cad.onshape.com/*"});
  let lastWindow = null;
  try { lastWindow = await browser.windows.getLastFocused({windowTypes: ["normal"]}); }
  catch { /* Closing windows can race the query. Let the caller request a URL. */ }
  return {
    context_version: 1,
    last_focused_window_id: lastWindow?.id ?? null,
    browser_window_focused: lastWindow?.focused ?? false,
    tabs: tabs.map(t => ({id: t.id, title: t.title, url: t.url,
                         active: t.active === true, window_id: t.windowId})),
  };
}
