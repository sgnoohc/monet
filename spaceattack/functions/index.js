const functions = require("firebase-functions");
const admin = require("firebase-admin");
admin.initializeApp();

/**
 * djb2 hash with salt, matching client-side _scoreToken().
 */
function scoreToken(name, sc, diff, lvl) {
  const salt = "Sp4ceAtt4ck";
  const raw = name + "|" + sc + "|" + diff + "|" + lvl + "|" + salt;
  let h = 5381;
  for (let i = 0; i < raw.length; i++) {
    h = ((h << 5) + h + raw.charCodeAt(i)) & 0xFFFFFFFF;
  }
  return (h >>> 0).toString(36);
}

/**
 * Max aliens that can appear from level 1 through `level`.
 * Grid sizes per level-in-cycle: 10, 18, 28, 32, 40.
 * Every 5th level is a boss (no alien grid).
 */
function maxAliens(level) {
  const gridSizes = [10, 18, 28, 32, 40];
  let total = 0;
  for (let lv = 1; lv <= level; lv++) {
    if (lv % 5 !== 0) {
      total += gridSizes[Math.min((lv - 1) % 5, gridSizes.length - 1)];
    }
  }
  return total;
}

exports.validateScore = functions.database
  .ref("/leaderboard/{difficulty}/{entryId}")
  .onCreate((snapshot, context) => {
    const entry = snapshot.val();
    const { difficulty, entryId } = context.params;
    const ref = snapshot.ref;

    // Backward compat: entries without session data are left alone
    if (!entry.s || typeof entry.s !== "string") {
      console.log(`SKIP ${entryId}: no session field (legacy entry)`);
      return null;
    }

    // 1. Field types and ranges
    if (typeof entry.name !== "string" || entry.name.length < 1 || entry.name.length > 12 ||
        typeof entry.score !== "number" || !Number.isInteger(entry.score) ||
        entry.score <= 0 || entry.score > 999999 ||
        typeof entry.level !== "number" || !Number.isInteger(entry.level) ||
        entry.level < 1 || entry.level > 99 ||
        typeof entry.v !== "string" || entry.v.length < 1) {
      console.log(`INVALID ${entryId}: malformed fields`);
      return ref.remove();
    }

    // 2. Integrity token
    const expectedToken = scoreToken(entry.name, entry.score, difficulty, entry.level);
    if (entry.v !== expectedToken) {
      console.log(`INVALID ${entryId}: bad integrity token`);
      return ref.remove();
    }

    // 3. Session string parse (14 dot-delimited integers)
    const parts = entry.s.split(".");
    if (parts.length !== 14) {
      console.log(`INVALID ${entryId}: session wrong part count (${parts.length})`);
      return ref.remove();
    }

    const nums = parts.map(Number);
    const [f, fk, bk, mk, ak, bd, bh, sf, pu, lp, ht, ts, pf, kc] = nums;

    // All fields must be non-negative integers
    for (let i = 0; i < nums.length; i++) {
      if (!Number.isFinite(nums[i]) || nums[i] < 0 || nums[i] !== Math.floor(nums[i])) {
        console.log(`INVALID ${entryId}: session field ${i} not a non-negative integer`);
        return ref.remove();
      }
    }

    // 4. Score decomposition
    const expectedScore = fk * 100 + bk * 150 + mk * 50 + ak * 75 + bh * 10;
    if (entry.score !== expectedScore) {
      console.log(`INVALID ${entryId}: score ${entry.score} != expected ${expectedScore}`);
      return ref.remove();
    }

    // 5. Kill ceiling
    const maxK = maxAliens(entry.level);
    if (fk + bk > maxK) {
      console.log(`INVALID ${entryId}: kills ${fk + bk} > max ${maxK}`);
      return ref.remove();
    }

    // 5b. Minimum kills: must have cleared all aliens on completed levels
    if (entry.level > 1) {
      const minK = maxAliens(entry.level - 1);
      if (fk + bk < minK) {
        console.log(`INVALID ${entryId}: kills ${fk + bk} < min ${minK}`);
        return ref.remove();
      }
    }

    // 5c. Bomber kill ceiling
    const gridSizes = [10, 18, 28, 32, 40];
    const gridCols = [5, 6, 7, 8, 8];
    let maxBombers = 0;
    for (let lv = 1; lv <= entry.level; lv++) {
      if (lv % 5 !== 0) {
        const gi = (lv - 1) % 5;
        const lc = gi + 1;
        const br = lc <= 2 ? 0 : lc <= 3 ? 1 : 2;
        maxBombers += br * gridCols[gi];
      }
    }
    if (bk > maxBombers) {
      console.log(`INVALID ${entryId}: bomber kills ${bk} > max ${maxBombers}`);
      return ref.remove();
    }

    // 6. Boss defeats (upper and lower bound)
    const maxBoss = Math.floor(entry.level / 5);
    const minBoss = entry.level > 5 ? Math.floor((entry.level - 1) / 5) : 0;
    if (bd > maxBoss || bd < minBoss) {
      console.log(`INVALID ${entryId}: boss defeats ${bd} out of range [${minBoss}, ${maxBoss}]`);
      return ref.remove();
    }

    // 6b. Boss HP exact validation
    const BOSS_HP = { easy: 40, medium: 60, difficult: 80, insane: 120, doomsday: 180 };
    const baseHp = BOSS_HP[difficulty];
    const hpMult = [0.4, 0.6, 0.8, 1.0, 1.2];
    let expectedBh = 0;
    for (let bi = 0; bi < bd; bi++) {
      const cycle = Math.floor(bi / 5);
      const bIdx = bi % 5;
      expectedBh += Math.round(baseHp * hpMult[bIdx] * Math.pow(1.15, cycle));
    }
    if (bh !== expectedBh) {
      console.log(`INVALID ${entryId}: bh ${bh} != expected ${expectedBh}`);
      return ref.remove();
    }

    // 7. Min frames (~1 sec/level absolute minimum)
    if (f < entry.level * 46) {
      console.log(`INVALID ${entryId}: frames ${f} < min ${entry.level * 46}`);
      return ref.remove();
    }

    // 8. Easy mode: no powerups
    if (difficulty === "easy" && pu > 0) {
      console.log(`INVALID ${entryId}: powerups on easy mode`);
      return ref.remove();
    }

    // 9. Timestamp: session start must be before the entry timestamp
    if (typeof entry.timestamp === "number" && ts >= entry.timestamp) {
      console.log(`INVALID ${entryId}: session start ${ts} >= submit time ${entry.timestamp}`);
      return ref.remove();
    }

    // 10. Shot count validation
    if (pf <= 0 && (fk + bk) > 0) {
      console.log(`INVALID ${entryId}: zero shots but has kills`);
      return ref.remove();
    }
    if (pf > Math.ceil(f / 2)) {
      console.log(`INVALID ${entryId}: shots ${pf} > max ${Math.ceil(f / 2)}`);
      return ref.remove();
    }

    // 11. Session integrity hash (djb2)
    const hashInput = String(f) + "|" + String(fk) + "|" +
                      String(bk) + "|" + String(bh) + "|" +
                      String(pf) + "|" + "X3vAlt9";
    let h = 5381;
    for (let i = 0; i < hashInput.length; i++) {
      h = ((h << 5) + h + hashInput.charCodeAt(i)) & 0xFFFFFFFF;
    }
    if (kc !== (h >>> 0)) {
      console.log(`INVALID ${entryId}: bad session integrity hash`);
      return ref.remove();
    }

    console.log(`VALID ${entryId}: ${entry.name} ${entry.score} on ${difficulty}`);
    return null;
  });
