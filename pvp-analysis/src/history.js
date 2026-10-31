// Every recording analysed so far, kept in history/ (one JSON file each), so each run only reads
// new recordings and the dashboard still has a recording's fights after the recording is deleted.
'use strict';
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

class History {
  constructor(dir) {
    this.dir = dir;
    fs.mkdirSync(dir, { recursive: true });
  }

  /** A recording's id: the same session gives the same id, whichever copy of the file it's read from. */
  static idFor(meta) {
    return crypto.createHash('sha1').update(`${meta.serverName}|${meta.date}|${meta.duration}`).digest('hex').slice(0, 12);
  }

  file(id) {
    return path.join(this.dir, `${id}.json`);
  }

  get(id) {
    try {
      return JSON.parse(fs.readFileSync(this.file(id), 'utf8'));
    } catch {
      return null;
    }
  }

  /** Save an analysis (written to a temporary file first, so a crash never leaves half of one). */
  put(entry) {
    const temp = `${this.file(entry.id)}.tmp`;
    fs.writeFileSync(temp, JSON.stringify(entry));
    fs.renameSync(temp, this.file(entry.id));
  }

  /** Every saved analysis, oldest recording first. */
  all() {
    return fs.readdirSync(this.dir).filter(f => f.endsWith('.json'))
      .map(f => {
        try {
          return JSON.parse(fs.readFileSync(path.join(this.dir, f), 'utf8'));
        } catch {
          return null;
        }
      })
      .filter(Boolean)
      .sort((a, b) => a.meta.date - b.meta.date);
  }
}

module.exports = { History };
