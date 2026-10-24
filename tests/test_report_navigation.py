"""Report navigation state tests in Node with a fake DOM/Plotly, not a browser."""
import json
import shutil
import subprocess

import pytest

from quant.report import _APP_JS, write_report
from tests.test_report import _run_dir


_HARNESS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
function element(value = '') { return {value, innerHTML: '', textContent: '', disabled: false}; }
const meta = [
  {id:'a', sym:'EURUSD', side:'LONG', pnlR:2, pnlUsd:10, exitType:'target', entryReason:'wick_touch'},
  {id:'b', sym:'EURUSD', side:'SHORT', pnlR:-1, pnlUsd:-5, exitType:'stop', entryReason:'wick_touch'},
  {id:'c', sym:'EURUSD', side:'LONG', pnlR:1, pnlUsd:5, exitType:'target', entryReason:'recovery_break'},
  {id:'d', sym:'EURUSD', side:'SHORT', pnlR:-1, pnlUsd:-5, exitType:'stop', entryReason:'recovery_break'},
  {id:'e', sym:'GBPUSD', side:'LONG', pnlR:1, pnlUsd:5, exitType:'target', entryReason:'wick_touch'}
].map(r => ({...r, entry:'2020-01-01 12:00', entryReasonLabel:r.entryReason}));
const bars = {t:['2020-01-01'], o:[1], h:[2], l:[0.5], c:[1.5]};
function context(row) {
  return {...row, exec:bars, reg:bars, entry:1, exit:1.5, sl:0.5, tp:2,
          entryTime:'2020-01-01', exitTime:'2020-01-02'};
}
const embedded = Object.fromEntries(meta.filter(r => r.id !== 'b').map(r => [r.id,context(r)]));
delete embedded.d.reg;
const payload = {meta, embedded, tf:{exec:'H4',reg:'Daily'}, emaExec:{fast:20,slow:100}, emaRegime:{fast:20,slow:100}};
const main = {pair:element('EURUSD'), filter:element('all'), exitFilter:element('all'), reasonFilter:element('all'),
              'figs-json':{textContent:'{}'}, 'trades-json':{textContent:JSON.stringify(payload)},
              'plotly-lib':{textContent:'/* fake Plotly */'}};
const plots = [];
let opens = 0, blocked = false, popup;
function makePopup() {
  const els = {}, handlers = {};
  return {closed:false, document:{title:'', open(){}, close(){},
    write(html){this.html=html;},
    getElementById(id){return els[id] ||= element();},
    addEventListener(type,handler){handlers[type]=handler;}, handlers},
    Plotly:{newPlot(el,data,layout){plots.push({data,layout}); el.textContent='chart';},
            purge(el){el.textContent='';}}};
}
const sandbox = {document:{getElementById(id){return main[id] ||= element();}}, Plotly:{},
  window:{open(){opens++; if(blocked) return null; popup=makePopup(); return popup;}}};
vm.createContext(sandbox);
vm.runInContext(APP_JS,sandbox);
const run = code => vm.runInContext(code,sandbox);
const el = id => popup.document.getElementById(id);
const key = (name,extra={}) => {
  const event={key:name, target:{closest(){return null;}}, prevented:false,
               preventDefault(){this.prevented=true;}, ...extra};
  popup.document.handlers.keydown(event);
  return event;
};
"""


def _run_js(tmp_path, scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable; navigation runtime test requires Node")
    script = tmp_path / "navigation.cjs"
    script.write_text("const APP_JS = " + json.dumps(_APP_JS) + ";\n" + _HARNESS + scenario,
                      encoding="utf-8")
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30,
                            encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr


def test_buttons_follow_filtered_order_and_keep_one_window(tmp_path):
    _run_js(tmp_path, r"""
run("openChart('a')");
assert.equal(el('tradecount').textContent,'Trade 1 of 4');
assert.equal(el('prevtrade').disabled,true);
assert.equal(el('nexttrade').disabled,false);
assert.ok(popup.document.html.includes('Previous trade'));
el('nexttrade').onclick();
assert.equal(popup.__tid,'b');
el('nexttrade').onclick();
assert.equal(popup.__tid,'c');
assert.ok(el('tradedetail').textContent.includes('recovery_break'));
assert.ok(plots.at(-1).layout.title.includes('EURUSD LONG $5'));
el('nexttrade').onclick();
assert.equal(popup.__tid,'d');
assert.equal(el('nexttrade').disabled,true);
run('navigateTrade(1)');
assert.equal(popup.__tid,'d');
el('prevtrade').onclick();
assert.equal(popup.__tid,'c');
assert.equal(opens,1);
""")


def test_arrow_keys_preserve_input_and_shortcut_behavior(tmp_path):
    _run_js(tmp_path, r"""
run("openChart('c')");
assert.equal(key('ArrowLeft').prevented,true);
assert.equal(popup.__tid,'b');
key('ArrowRight');
assert.equal(popup.__tid,'c');
for (const extra of [{ctrlKey:true},{altKey:true},{metaKey:true},{shiftKey:true},{defaultPrevented:true},
                     {target:{isContentEditable:true}}, {target:{closest(){return {};}}}]) {
  assert.equal(key('ArrowRight',extra).prevented,false);
  assert.equal(popup.__tid,'c');
}
assert.equal(key('Enter').prevented,false);
assert.equal(popup.__tid,'c');
""")


def test_filter_changes_resync_selection_and_handle_empty_lists(tmp_path):
    _run_js(tmp_path, r"""
run("openChart('a')");
main.filter.value='winners'; main.filter.onchange();
assert.equal(el('tradecount').textContent,'Trade 1 of 2');
el('nexttrade').onclick();
assert.equal(popup.__tid,'c');
main.reasonFilter.value='wick_touch'; main.reasonFilter.onchange();
assert.equal(popup.__tid,'a');
assert.equal(el('tradecount').textContent,'Trade 1 of 1');
assert.ok(el('prevtrade').disabled && el('nexttrade').disabled);
main.exitFilter.value='stop'; main.exitFilter.onchange();
assert.equal(popup.__tid,null);
assert.equal(el('tradecount').textContent,'Trade 0 of 0');
assert.ok(el('pop-chart').textContent.includes('No trades match'));
assert.equal(el('tradedetail').textContent,'');
key('ArrowRight');
assert.equal(popup.__tid,null);
main.exitFilter.value='all'; main.exitFilter.onchange();
assert.equal(popup.__tid,'a');
main.pair.value='GBPUSD'; main.pair.onchange();
assert.equal(popup.__tid,'e');
assert.ok(el('tradedetail').textContent.startsWith('GBPUSD'));
assert.equal(opens,1);
""")


def test_missing_charts_blocked_popup_and_reopening(tmp_path):
    _run_js(tmp_path, r"""
blocked=true; run("openChart('a')");
assert.ok(main.msg.textContent.includes('popup blocked'));
run('navigateTrade(1)');
blocked=false; run("openChart('a')");
run('navigateTrade(1)');
assert.equal(popup.__tid,'b');
assert.ok(el('pop-chart').textContent.includes('Chart not embedded'));
assert.equal(el('tfbtns').innerHTML,'');
assert.equal(el('tradecount').textContent,'Trade 2 of 4');
run('navigateTrade(1)');
assert.equal(popup.__tid,'c');
assert.equal(el('pop-chart').textContent,'chart');
popup.closed=true;
run('navigateTrade(1)');
run("openChart('d')");
assert.equal(popup.__tid,'d');
assert.equal(opens,3);
""")


def test_timeframe_selection_survives_navigation_with_fallback(tmp_path):
    _run_js(tmp_path, r"""
run("openChart('a','reg')");
assert.ok(plots.at(-1).layout.title.includes('Daily'));
run('navigateTrade(1)'); // missing quote data must not forget the selected timeframe
run('navigateTrade(1)');
assert.equal(popup.__tid,'c');
assert.ok(plots.at(-1).layout.title.includes('Daily'));
run('navigateTrade(1)'); // this trade has no regime chart
assert.ok(plots.at(-1).layout.title.includes('H4'));
assert.equal(run('curTf'),'exec');
""")


def test_report_contains_navigation_without_rewriting_saved_inputs(tmp_path):
    run, data, _ = _run_dir(tmp_path)
    original = {p.name: p.read_bytes() for p in run.iterdir() if p.is_file()}
    assert write_report(run, data)
    html = (run / "report.html").read_text(encoding="utf-8")
    assert 'id="prevtrade"' in html and 'id="nexttrade"' in html
    assert 'id="tradecount"' in html and "ArrowLeft" in html and "ArrowRight" in html
    assert all((run / name).read_bytes() == content for name, content in original.items())
