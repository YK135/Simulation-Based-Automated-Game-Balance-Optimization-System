/* ═══════════════════════════════════════════════════════════
   state.js — 전역 상태 + 이미지/아이콘 매핑 상수

   - state: 런타임 상태 (player, inBattle 등)
   - JOB_ICONS / ENEMY_ICONS: 이모지 폴백 (이미지 없을 때)
   - JOB_PORTRAITS / JOB_SPRITES / ENEMY_SPRITES: 이미지 경로 매핑

   이미지 사용 시:
     1) static/img/ 폴더에 PNG 배치
     2) index.html의 해당 자리 <img> 태그 주석 풀기
     3) 아래 PORTRAITS/SPRITES 매핑은 그대로 활용 가능
   ═══════════════════════════════════════════════════════════ */

let state = {
    player: null,
    inBattle: false,
    battleState: null,
    aiLevel: 'normal',
    exploreTurn: 0,
};

// ── 이모지 폴백 (이미지 못 넣었을 때 표시용) ──
const JOB_ICONS = { '전사':'⚔', '마법사':'⚡', '탱커':'🛡', '도적':'🗡' };
const ENEMY_ICONS = {
    '고블린':'👺', '박쥐':'🦇', '슬라임':'🟢',
    '골렘':'🗿', '유령':'👻', '암살자':'🥷',
    '중간 보스':'👹', '최종 보스':'🐉',
};

/* ═════════════════════════════════════════════════════════
   ▼ 이미지 사용 시 매핑 활성화 ▼
   <img> 태그로 교체했을 때 src 동적 변경에 사용.

const JOB_PORTRAITS = {
    '전사':   '/img/portrait_warrior.png',
    '마법사': '/img/portrait_mage.png',
    '탱커':   '/img/portrait_tanker.png',
    '도적':   '/img/portrait_rogue.png',
};
const JOB_SPRITES = {
    '전사':   '/img/sprite_warrior.png',
    '마법사': '/img/sprite_mage.png',
    '탱커':   '/img/sprite_tanker.png',
    '도적':   '/img/sprite_rogue.png',
};
const ENEMY_SPRITES = {
    '고블린':   '/img/sprite_goblin.png',
    '박쥐':     '/img/sprite_bat.png',
    '슬라임':   '/img/sprite_slime.png',
    '골렘':     '/img/sprite_golem.png',
    '유령':     '/img/sprite_ghost.png',
    '암살자':   '/img/sprite_assassin.png',
    '중간 보스': '/img/sprite_midboss.png',
    '최종 보스': '/img/sprite_finalboss.png',
};
   ═════════════════════════════════════════════════════════ */