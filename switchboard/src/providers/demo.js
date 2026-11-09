// Fake conversations for trying the UI without any accounts (npm run demo).
const { EventEmitter } = require('events');

const MIN = 60000;

const SEED = [
  { id: 'd1', service: 'discord', kind: 'dm', title: 'Alex Rivera', subtitle: 'Direct message', ago: 2, unread: true, count: 2,
    msgs: [['Alex Rivera', 'are you coming to the lab meeting?', 9], ['me', 'yes, running 5 min late', 6], ['me', 'grabbing coffee first, want one?', 5], ['Alex Rivera', 'no worries, saving you a seat', 2], ['Alex Rivera', 'yes please! oat latte', 2, 2]] },
  { id: 'm1', service: 'mattermost', kind: 'channel', title: '#detector-ops', subtitle: 'ATLAS', ago: 7, mentions: 1,
    msgs: [['Sam Okafor', 'Run 4521 finished, data quality looks good', 40], ['Priya Nair', '@me can you check the calibration plots?', 7]] },
  { id: 't1', service: 'mattermost', kind: 'dm', title: 'Jordan Lee', subtitle: 'Direct message', ago: 25,
    msgs: [['Jordan Lee', 'sent you the slides for Thursday', 30], ['me', 'thanks, will review tonight', 25]] },
  { id: 'd2', service: 'discord', kind: 'channel', title: '#general', subtitle: 'Gator Physics', ago: 55, unread: true, count: 14,
    msgs: [['Casey', 'anyone have notes from PHY 4604?', 70], ['Morgan', 'I can share mine after class', 55]] },
  { id: 'm2', service: 'mattermost', kind: 'channel', title: '#town-square', subtitle: 'CERN', ago: 180,
    msgs: [['Robin', 'Reminder: cafeteria closes early Friday', 180]] },
  { id: 's1', service: 'slack', kind: 'channel', title: '#analysis', subtitle: 'Physics Lab', ago: 15, unread: true, count: 3,
    msgs: [['Dana Kim', 'new histograms are up on the shared drive', 15]] },
  { id: 's2', service: 'slack', kind: 'dm', title: 'Chris Patel', subtitle: 'Direct message', ago: 95,
    msgs: [['Chris Patel', 'can we move our 1:1 to 3pm?', 95]] },
  { id: 'd3', service: 'discord', kind: 'group', title: 'Weekend hike', subtitle: 'Group', ago: 60 * 26,
    msgs: [['Taylor', 'Saturday 8am at the trailhead?', 60 * 27], ['me', "I'm in", 60 * 26]] },
];

class DemoProvider extends EventEmitter {
  constructor() {
    super();
    this.id = 'demo';
    this.label = 'Demo';
    this.convs = new Map();
    this.messages = new Map();
    this.counter = 0;
  }

  connect() {
    const now = Date.now();
    for (const s of SEED) {
      this.convs.set(s.id, {
        id: s.id, key: `demo:${s.id}`, provider: 'demo', service: s.service, kind: s.kind,
        title: s.title, subtitle: s.subtitle, avatar: null, muted: false,
        lastActivity: now - s.ago * MIN, unread: !!s.unread || !!s.mentions, mentions: s.mentions || 0,
        unreadCount: s.count || s.mentions || 0,
      });
      const msgs = s.msgs.map(([who, text, ago]) => this.makeMessage(who, text, now - ago * MIN));
      if (s.id === 'd1') {
        msgs[3].reactions = [{ key: '❤️', emoji: '❤️', name: '❤️', imageUrl: null, count: 1, me: false }];
        msgs[0].text += ' :partycat:';
        msgs[0].customEmoji = { partycat: 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5" fill="orange"/></svg>') };
      }
      // An optional 4th field is the index of the message being replied to.
      s.msgs.forEach(([, , , replyIdx], i) => {
        const ref = msgs[replyIdx];
        if (ref) msgs[i].replyTo = { id: ref.id, author: ref.author.name, text: ref.text };
      });
      this.messages.set(s.id, msgs);
    }
    this.emit('status', { state: 'connected', user: 'demo' });
    this.emit('conversations', this.conversations());
    this.timer = setInterval(() => {
      const conv = this.convs.get('d1');
      const message = this.makeMessage('Alex Rivera', 'just checking in 👋', Date.now());
      this.messages.get('d1').push(message);
      conv.lastActivity = message.ts;
      conv.unread = true;
      conv.unreadCount += 1;
      this.emit('message', { convId: 'd1', message });
    }, 45000);
  }

  disconnect() {
    clearInterval(this.timer);
  }

  conversations() {
    return [...this.convs.values()];
  }

  makeMessage(who, text, ts) {
    const isSelf = who === 'me';
    return {
      id: `demo-${++this.counter}`, ts, isSelf, mentionsMe: text.includes('@me'), text, attachments: [],
      author: { id: isSelf ? 'me' : who, name: isSelf ? 'You' : who, avatar: null },
    };
  }

  async fetchMessages(convId, before) {
    return before ? [] : [...this.messages.get(convId)];
  }

  async send(convId, text) {
    const message = this.makeMessage('me', text, Date.now());
    this.messages.get(convId).push(message);
    this.convs.get(convId).lastActivity = message.ts;
    return message;
  }

  async react(convId, messageId, value, add) {
    return { key: value, emoji: value, name: value, imageUrl: null, count: 1, me: add };
  }

  async searchGifs() {
    throw new Error('GIF search uses your Discord account (not available in demo mode).');
  }

  reconnect() {}

  async upload(convId, files, text) {
    const message = this.makeMessage('me', text, Date.now());
    message.attachments = files.map(f => ({ name: f.name, size: f.data.length, url: null, isImage: false }));
    this.messages.get(convId).push(message);
    return message;
  }

  async markRead(convId) {
    const conv = this.convs.get(convId);
    conv.unread = false;
    conv.unreadCount = 0;
    conv.mentions = 0;
  }
}

module.exports = DemoProvider;
