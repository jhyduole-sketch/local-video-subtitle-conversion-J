const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const state = require('../src/subtitle_tool/web_assets/job_state.js');

// 仅替代浏览器 DOM、网络与时钟；被测代码为实际应用脚本。
// Replace only browser DOM, networking and clocks; execute the actual app script.
function browser() {
  const nodes = new Map();
  const requests = [];
  const timers = new Map();
  let timerId = 0;
  function element() {
    let text = '';
    return {
      value: '', checked: false, disabled: false, dataset: {}, style: {}, children: [], writes: 0,
      classList: { add() {}, remove() {} },
      get textContent() { return text + this.children.map((child) => child.textContent).join(''); },
      set textContent(value) { text = value; this.children = []; this.writes += 1; },
      set innerHTML(value) { text = value; this.children = []; },
      get innerHTML() { return text; },
      appendChild(child) { this.children.push(child); return child; },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { text = ''; this.children = children; this.writes += 1; },
      addEventListener() {}, querySelectorAll() { return []; },
      setAttribute() {}, getAttribute() { return ''; }, scrollIntoView() {},
    };
  }
  const document = {
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, element());
      return nodes.get(selector);
    },
    addEventListener() {},
    createTextNode(text) { return { textContent: text, appendData(value) { this.textContent += value; } }; },
  };
  const window = {
    subtitleJobState: state,
    subtitleLanguageCatalog: { languagePickerModes: { 'z-ai': { languages: [], hint: '' } } },
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    setInterval() { return ++timerId; }, clearInterval() {},
  };
  const context = vm.createContext({ window, document, console, URLSearchParams,
    fetch(url, options) {
      return new Promise((resolve, reject) => requests.push({ url, options, reject,
        respond(data, ok = true) { resolve({ ok, json: async () => data }); } }));
    },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../src/subtitle_tool/web_assets/app.js'), 'utf8'), context);
  requests.splice(0);
  return { nodes, requests, timers,
    run(code) { return vm.runInContext(code, context); },
    async tick() {
      const [id, callback] = timers.entries().next().value;
      timers.delete(id);
      return callback();
    },
  };
}
function job(id, logs, offset, total, status = 'running') {
  return { id, status, logs, logsIncluded: true, logOffset: offset, nextLogOffset: offset + logs.length,
    logTotal: total, hasMoreLogs: offset + logs.length < total, progress: 20, createdAt: 1 };
}

test('history view drains terminal logs in suffix chunks and appends without replacing existing DOM', async () => {
  const app = browser();
  const viewing = app.run('viewHistoryJob("a")');
  assert.match(app.requests[0].url, /logOffset=0&logLimit=200/);
  app.requests.shift().respond(job('a', ['first'], 0, 2, 'succeeded'));
  await viewing;
  const logs = app.nodes.get('#logBox');
  const writes = logs.writes;
  const draining = app.tick();
  assert.match(app.requests[0].url, /logOffset=1&logLimit=200/);
  app.requests.shift().respond(job('a', ['last'], 1, 2, 'succeeded'));
  await draining;
  assert.equal(logs.textContent, 'first\nlast');
  assert.equal(logs.writes, writes);
});

test('metadata adoption preserves rendered logs and cursor', async () => {
  const app = browser();
  const viewing = app.run('viewHistoryJob("a")');
  app.requests.shift().respond(job('a', ['first'], 0, 1));
  await viewing;
  app.run('adoptActiveJob({id: "a", status: "running", logs: [], logsIncluded: false})');
  assert.equal(app.nodes.get('#logBox').textContent, 'first');
  const next = app.tick();
  assert.match(app.requests[0].url, /logOffset=1/);
  app.requests.shift().respond(job('a', ['second'], 1, 2));
  await next;
  assert.equal(app.nodes.get('#logBox').textContent, 'first\nsecond');
});

test('switching history selections rejects a late old response', async () => {
  const app = browser();
  const old = app.run('viewHistoryJob("a")');
  const oldRequest = app.requests.shift();
  const current = app.run('viewHistoryJob("b")');
  app.requests.shift().respond(job('b', ['current'], 0, 1, 'succeeded'));
  await current;
  oldRequest.respond(job('a', ['stale'], 0, 1, 'succeeded'));
  await old;
  assert.equal(app.nodes.get('#logBox').textContent, 'current');
});

test('history pagination latest request wins and metadata does not hijack old-job viewing', async () => {
  const app = browser();
  const viewing = app.run('viewHistoryJob("old")');
  app.requests.shift().respond(job('old', ['old logs'], 0, 1, 'failed'));
  await viewing;
  app.requests.splice(0);
  const first = app.run('loadHistory(0)');
  const firstRequest = app.requests.shift();
  const second = app.run('loadHistory(50)');
  app.requests.shift().respond({ jobs: [{id:'page2', status:'failed'}], activeJob: {id:'live', status:'running', logsIncluded:false}, offset:50, limit:50, total:101, hasMore:true });
  await second;
  firstRequest.respond({ jobs:[{id:'page1',status:'failed'}], activeJob:null, offset:0, limit:50,total:101,hasMore:true });
  await first;
  assert.match(app.nodes.get('#historyList').innerHTML, /page2/);
  assert.doesNotMatch(app.nodes.get('#historyList').innerHTML, /page1/);
  assert.equal(app.nodes.get('#logBox').textContent, 'old logs');
  assert.equal(app.nodes.get('#runButton').disabled, true);
});

test('reconnecting keeps the last received log cursor and appends the recovered suffix once', async () => {
  const app = browser();
  const viewing = app.run('viewHistoryJob("a")');
  app.requests.shift().respond(job('a', ['first'], 0, 1));
  await viewing;
  const failing = app.tick();
  app.requests.shift().reject(new Error('offline'));
  await failing;
  const retry = app.tick();
  assert.match(app.requests[0].url, /logOffset=1/);
  app.requests.shift().respond(job('a', ['second'], 1, 2));
  await retry;
  assert.equal(app.nodes.get('#logBox').textContent, 'first\nsecond');
});

test('active completion unlocks controls while viewing terminal history without replacing its page or logs', async () => {
  const app = browser();
  app.run('currentJobId = "live"');
  const viewing = app.run('viewHistoryJob("old")');
  app.requests.shift().respond(job('old', ['historical log'], 0, 1, 'succeeded'));
  await viewing;
  const listRequest = app.requests.find((request) => request.url.startsWith('/api/jobs?'));
  listRequest.respond({ jobs: [{ id: 'page2', status: 'succeeded' }], activeJob: { id: 'live', status: 'running', logsIncluded: false }, offset: 50, limit: 50, total: 70, hasMore: false });
  await new Promise(setImmediate);
  app.requests.splice(0);
  assert.equal(app.nodes.get('#runButton').disabled, true);
  assert.equal(app.timers.size, 1);
  const monitoring = app.tick();
  assert.equal(app.requests[0].url, '/api/jobs?limit=1');
  app.requests.shift().respond({ jobs: [], activeJob: null, offset: 0, limit: 1, total: 70, hasMore: true });
  await monitoring;
  assert.equal(app.nodes.get('#runButton').disabled, false);
  assert.equal(app.nodes.get('#stopButton').disabled, true);
  assert.equal(app.nodes.get('#logBox').textContent, 'historical log');
  assert.match(app.nodes.get('#historyList').innerHTML, /page2/);
  assert.match(app.nodes.get('#historyPageSummary').textContent, /2 \/ 2/);
  assert.equal(app.timers.size, 0);
});

test('late background metadata cannot unlock a newly selected active job or schedule duplicate monitors', async () => {
  const app = browser();
  app.run('currentJobId = "live"');
  const viewing = app.run('viewHistoryJob("old")');
  app.requests.shift().respond(job('old', ['historical log'], 0, 1, 'succeeded'));
  await viewing;
  app.requests.splice(0);
  app.run('adoptActiveJob({ id: "live", status: "running", logsIncluded: false })');
  app.run('adoptActiveJob({ id: "live", status: "running", logsIncluded: false })');
  assert.equal(app.timers.size, 1);
  const monitoring = app.tick();
  const stale = app.requests.shift();
  const selected = app.run('viewHistoryJob("live")');
  app.requests.shift().respond(job('live', ['live log'], 0, 1));
  await selected;
  stale.respond({ jobs: [], activeJob: null, offset: 0, limit: 1, total: 0, hasMore: false });
  await monitoring;
  assert.equal(app.nodes.get('#runButton').disabled, true);
  assert.equal(app.nodes.get('#logBox').textContent, 'live log');
  assert.equal(app.timers.size, 1);
});

test('log display keeps a bounded tail and links a complete download', () => {
  const app = browser();
  app.run('selectJob("large"); appendJobLogs({lines: Array.from({length:1200}, (_, i) => `line-${i}`)})');
  const text = app.nodes.get('#logBox').textContent;
  assert.equal(text.split('\n').length, 1000);
  assert.equal(text.split('\n')[0], 'line-200');
  assert.match(app.nodes.get('#logWindowHint').textContent, /1000/);
  assert.equal(app.nodes.get('#downloadLogLink').href, '/api/jobs/large/logs');
});
