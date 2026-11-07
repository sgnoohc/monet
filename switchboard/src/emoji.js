// Common emoji shortcodes, as used by Slack and Mattermost (":thumbsup:"),
// and the reverse lookup for reacting with a Unicode emoji.
const SHORTCODES = {
  '+1': '👍', thumbsup: '👍', '-1': '👎', thumbsdown: '👎',
  heart: '❤️', heart_eyes: '😍', orange_heart: '🧡', yellow_heart: '💛', green_heart: '💚', blue_heart: '💙', purple_heart: '💜', broken_heart: '💔',
  joy: '😂', laughing: '😆', satisfied: '😆', smile: '😄', smiley: '😃', grinning: '😀', grin: '😁', rofl: '🤣', sweat_smile: '😅',
  slightly_smiling_face: '🙂', blush: '😊', wink: '😉', upside_down_face: '🙃', smirk: '😏', relieved: '😌', innocent: '😇',
  open_mouth: '😮', astonished: '😲', scream: '😱', flushed: '😳', exploding_head: '🤯',
  cry: '😢', sob: '😭', disappointed: '😞', pensive: '😔', confused: '😕', worried: '😟', frowning: '😦', weary: '😩', tired_face: '😫',
  angry: '😠', rage: '😡', triumph: '😤', neutral_face: '😐', expressionless: '😑', no_mouth: '😶', rolling_eyes: '🙄', grimacing: '😬',
  thinking_face: '🤔', thinking: '🤔', face_with_monocle: '🧐', nerd_face: '🤓', sunglasses: '😎', partying_face: '🥳', star_struck: '🤩',
  sleeping: '😴', yawning_face: '🥱', mask: '😷', skull: '💀', ghost: '👻', poop: '💩', hankey: '💩', clown_face: '🤡',
  pray: '🙏', clap: '👏', raised_hands: '🙌', wave: '👋', ok_hand: '👌', muscle: '💪', point_up: '☝️', point_right: '👉', v: '✌️',
  crossed_fingers: '🤞', handshake: '🤝', eyes: '👀', see_no_evil: '🙈', facepalm: '🤦', face_palm: '🤦', shrug: '🤷',
  fire: '🔥', tada: '🎉', sparkles: '✨', star: '⭐', zap: '⚡', boom: '💥', '100': '💯', rocket: '🚀', trophy: '🏆', medal: '🏅',
  white_check_mark: '✅', heavy_check_mark: '✔️', ballot_box_with_check: '☑️', x: '❌', warning: '⚠️', question: '❓', exclamation: '❗',
  bulb: '💡', memo: '📝', pushpin: '📌', calendar: '📆', coffee: '☕', beer: '🍺', pizza: '🍕', cake: '🍰', birthday: '🎂',
  sun_with_face: '🌞', sunny: '☀️', rainbow: '🌈', snowflake: '❄️', cat: '🐱', dog: '🐶', heart_on_fire: '❤️‍🔥', salute: '🫡',
};

// Unicode -> shortcode, preferring the first name listed above.
const NAMES = {};
for (const [name, emoji] of Object.entries(SHORTCODES)) NAMES[emoji] ??= name;

const baseName = name => name.replace(/::skin-tone-\d$/, '');

function shortcodeToEmoji(name) {
  return SHORTCODES[baseName(name)] || null;
}

function nameForEmoji(value) {
  return NAMES[value] || value;
}

function replaceShortcodes(text) {
  return text.replace(/:([\w+-]+(?:::skin-tone-\d)?):/g, (match, name) => shortcodeToEmoji(name) || match);
}

module.exports = { shortcodeToEmoji, nameForEmoji, replaceShortcodes };
