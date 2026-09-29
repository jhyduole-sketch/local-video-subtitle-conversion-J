(function (root) {
  // 请求代次隔离任务切换及重试，游标只在日志成功接收后前进。
  // Request generations isolate selections and retries; cursors advance only after received logs.
  class JobStream {
    constructor() {
      this.jobId = '';
      this.offset = 0;
      this.generation = 0;
      this.request = 0;
    }

    select(jobId, reset = false) {
      if (this.jobId === jobId && !reset) return false;
      this.jobId = jobId;
      this.offset = 0;
      this.generation += 1;
      this.request += 1;
      return true;
    }

    begin() {
      return { jobId: this.jobId, generation: this.generation, request: ++this.request, offset: this.offset };
    }

    isCurrent(token) {
      return token.jobId === this.jobId && token.generation === this.generation && token.request === this.request;
    }

    consume(token, job) {
      if (!this.isCurrent(token) || job.id !== this.jobId || job.logsIncluded === false) return { accepted: false };
      this.request += 1;
      const lines = Array.isArray(job.logs) ? job.logs : [];
      const start = Number.isInteger(job.logOffset) ? job.logOffset : 0;
      const total = Number.isInteger(job.logTotal) ? job.logTotal : start + lines.length;
      // 服务端游标回退时从头重载；不可跨过未收到的日志。
      // Reload from zero after a server cursor reset; never skip unreceived logs.
      if ((total < this.offset && start !== 0) || start > this.offset) {
        this.offset = 0;
        return { accepted: true, reset: true, lines: [], hasMore: total > 0 };
      }
      const reset = start === 0 && this.offset > 0;
      if (reset) this.offset = 0;
      const suffix = lines.slice(Math.max(0, this.offset - start));
      this.offset += suffix.length;
      return { accepted: true, reset, lines: suffix, hasMore: Boolean(job.hasMoreLogs) || this.offset < total };
    }
  }

  class HistoryPages {
    constructor(limit = 50) {
      this.limit = limit;
      this.offset = 0;
      this.total = 0;
      this.hasMore = false;
      this.request = 0;
    }

    begin(offset = this.offset) {
      return { request: ++this.request, offset: Math.max(0, offset) };
    }

    isCurrent(token) {
      return token.request === this.request;
    }

    accept(token, data) {
      if (!this.isCurrent(token)) return false;
      this.offset = Number.isInteger(data.offset) ? data.offset : token.offset;
      this.total = Number.isInteger(data.total) ? data.total : (data.jobs || []).length;
      this.hasMore = Boolean(data.hasMore);
      return true;
    }
  }

  const api = { JobStream, HistoryPages };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.subtitleJobState = api;
})(typeof window !== 'undefined' ? window : globalThis);
