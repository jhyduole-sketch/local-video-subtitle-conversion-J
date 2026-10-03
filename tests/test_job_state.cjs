const test = require('node:test');
const assert = require('node:assert/strict');
const { JobStream, HistoryPages } = require('../src/subtitle_tool/web_assets/job_state.js');

function chunk(offset, logs, total, status = 'running') {
  return { id: 'a', status, logs, logsIncluded: true, logOffset: offset,
    nextLogOffset: offset + logs.length, logTotal: total, hasMoreLogs: offset + logs.length < total };
}

test('suffix chunks advance exactly once and keep draining after completion', () => {
  const stream = new JobStream();
  stream.select('a');
  const first = stream.begin();
  assert.deepEqual(stream.consume(first, chunk(0, ['first', 'second'], 3, 'succeeded')).lines, ['first', 'second']);
  assert.equal(stream.offset, 2);
  assert.equal(stream.consume(first, chunk(0, ['first', 'second'], 3)).accepted, false);
  const next = stream.begin();
  assert.equal(next.offset, 2);
  const tail = stream.consume(next, chunk(2, ['third'], 3, 'succeeded'));
  assert.deepEqual(tail.lines, ['third']);
  assert.equal(tail.hasMore, false);
  assert.equal(stream.offset, 3);
});

test('metadata refresh preserves logs cursor and in-flight suffix request', () => {
  const stream = new JobStream();
  stream.select('a');
  stream.consume(stream.begin(), chunk(0, ['first'], 1));
  const suffix = stream.begin();
  assert.equal(stream.select('a'), false);
  assert.equal(stream.isCurrent(suffix), true);
  assert.equal(stream.offset, 1);
  assert.equal(stream.consume(suffix, { id: 'a', logs: [], logsIncluded: false }).accepted, false);
  assert.equal(stream.offset, 1);
});

test('task switch and refresh reject late responses even when reselecting same job', () => {
  const stream = new JobStream();
  stream.select('a');
  const first = stream.begin();
  stream.select('b');
  stream.select('a');
  assert.equal(stream.consume(first, chunk(0, ['stale'], 1)).accepted, false);
  const refreshed = stream.begin();
  stream.select('a', true);
  assert.equal(stream.consume(refreshed, chunk(0, ['stale'], 1)).accepted, false);
  assert.equal(stream.offset, 0);
});

test('newer requests reject stale errors and out-of-order payloads', () => {
  const stream = new JobStream();
  stream.select('a');
  const old = stream.begin();
  const latest = stream.begin();
  assert.equal(stream.isCurrent(old), false);
  assert.equal(stream.consume(old, chunk(0, ['stale'], 1)).accepted, false);
  assert.deepEqual(stream.consume(latest, chunk(0, ['latest'], 1)).lines, ['latest']);
});

test('server truncation resets cursor and reloads retained logs without gaps', () => {
  const stream = new JobStream();
  stream.select('a');
  stream.consume(stream.begin(), chunk(0, ['old1', 'old2', 'old3'], 3));
  const reset = stream.consume(stream.begin(), chunk(1, [], 1));
  assert.equal(reset.reset, true);
  assert.equal(reset.hasMore, true);
  assert.equal(stream.offset, 0);
  const reloaded = stream.consume(stream.begin(), chunk(0, ['new1'], 1));
  assert.deepEqual(reloaded.lines, ['new1']);
  assert.equal(stream.offset, 1);
});

test('server restart at zero replaces previous log stream', () => {
  const stream = new JobStream();
  stream.select('a');
  stream.consume(stream.begin(), chunk(0, ['old'], 1));
  const reset = stream.consume(stream.begin(), chunk(0, ['new1', 'new2'], 2));
  assert.equal(reset.reset, true);
  assert.deepEqual(reset.lines, ['new1', 'new2']);
  assert.equal(stream.offset, 2);
});

test('failed fetch retry starts at last received offset', () => {
  const stream = new JobStream();
  stream.select('a');
  stream.consume(stream.begin(), chunk(0, ['first'], 2));
  stream.begin();
  assert.equal(stream.begin().offset, 1);
  const retry = stream.consume(stream.begin(), chunk(1, ['second'], 2));
  assert.deepEqual(retry.lines, ['second']);
});

test('history paging ignores stale page responses and resets to first page', () => {
  const pages = new HistoryPages(50);
  const first = pages.begin(0);
  const second = pages.begin(50);
  assert.equal(pages.accept(first, { offset: 0, total: 120, hasMore: true }), false);
  assert.equal(pages.accept(second, { offset: 50, total: 120, hasMore: true }), true);
  assert.equal(pages.offset, 50);
  assert.equal(pages.total, 120);
  assert.equal(pages.hasMore, true);
  const reset = pages.begin(0);
  assert.equal(pages.accept(reset, { offset: 0, total: 0, hasMore: false }), true);
  assert.equal(pages.offset, 0);
  assert.equal(pages.total, 0);
  assert.equal(pages.hasMore, false);
});

test('truncated memory-only streams advance to retained absolute offset', () => {
  const stream = new JobStream();
  stream.select('a');
  const chunk = stream.consume(stream.begin(), {id:'a', logs:['tail'], logOffset:100, logTotal:101, logTruncated:true});
  assert.deepEqual(chunk.lines, ['tail']);
  assert.equal(stream.offset, 101);
  assert.equal(chunk.reset, true);
});
