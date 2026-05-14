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
 
    // ── 비동기 작업 락 (Race condition 방지) ──
    exploring: false,
    battleProcessing: false,
 
    // ── 시작 플로우 상태 (3단계 모달) ──
    selectedJob: '전사',
    isEmailAuth: false,
    userEmail: null,
};

const JOB_DATA = {
    '전사': {
        name: 'WARRIOR',
        icon: '⚔',
        tags: ['균형형', '물리'],
        description:
            '높은 HP와 안정적인 물리 데미지를 갖춘 균형형 전사. ' +
            '초보자에게 가장 적합하며, 모든 상황에서 안정적인 성능을 발휘한다.',
        passive: '【패시브】 3회 공격마다 최대 HP 10% 자동 회복',
        // 이미지로 교체 시 사용:
        // portrait_image: '/img/portrait_warrior.png'
    },
    '마법사': {
        name: 'MAGE',
        icon: '✦',
        tags: ['마법', '효율형'],
        description:
            '강력한 마법 공격과 효율적인 MP 관리. ' +
            '슬라임 같은 마법 약점 적에게 극대화된 데미지를 입힐 수 있다.',
        passive: '【패시브】 모든 스킬 MP 비용 30% 영구 감소',
    },
    '탱커': {
        name: 'TANKER',
        icon: '▣',
        tags: ['방어형', '회복'],
        description:
            '높은 방어력과 피격 시 자원 회복. ' +
            '오래 버티며 적의 공격을 견뎌내는 인내형 직업.',
        passive: '【패시브】 물리 피격 시 MP 회복 / 마법 피격 시 HP 회복 (각 10%)',
    },
    '도적': {
        name: 'ROGUE',
        icon: '✧',
        tags: ['속도형', '치명타'],
        description:
            '빠른 행동력과 치명타 특화. ' +
            '높은 SPD로 선공을 잡고 크리티컬로 단숨에 적을 무력화한다.',
        passive: '【패시브】 치명타 발생 시 70% 확률로 방어력 50% 무시',
    },
};

// ── 이모지 폴백 (이미지 못 넣었을 때 표시용) ──
const JOB_ICONS = { '전사':'⚔', '마법사':'⚡', '탱커':'🛡', '도적':'🗡' };
const ENEMY_ICONS = {
    '고블린':'👺', '박쥐':'🦇', '슬라임':'🟢',
    '골렘':'🗿', '유령':'👻', '암살자':'🥷',
    '사제':'⚕',
    '중간 보스':'👹', '최종 보스':'🐉',
};

// ═══════════════════════════════════════════════════════════
// 상태별 이미지 매핑 (3계층)
// ───────────────────────────────────────────────────────────
// 1. player_panel  : 좌측 플레이어 패널 (idle / hurt / happy)
// 2. player_battle : 배틀필드 플레이어 (idle / attack / skill / hurt / dead)
// 3. enemy_battle  : 배틀필드 몬스터 (idle / attack / skill / hurt / dead)
//
// 파일 경로 규칙:
//   /img/{section}/{name}_{state}.png
//   예: /img/player_panel/warrior_idle.png
//       /img/player_battle/warrior_attack.png
//       /img/enemy_battle/goblin_dead.png
//
// 이미지 없는 상태:
//   - getCharImage()가 자동 폴백: 해당 상태 없으면 idle 사용
//   - idle도 없으면 null 반환 → 이모지(JOB_ICONS/ENEMY_ICONS) 표시
//
// 이미지 권장 사이즈:
//   - player_panel:  256x256 또는 512x512 (정사각형)
//   - player_battle: 96x96 ~ 256x256 (투명배경 PNG)
//   - enemy_battle:  96x96 ~ 256x256 (투명배경 PNG)
// ═══════════════════════════════════════════════════════════

const CHAR_IMAGES = {

    // ── 좌측 플레이어 패널 (3상태) ──
    player_panel: {
        '전사': {
            idle:  '/img/face/warrior_face_A.png',
            hurt:  '/img/player_panel/warrior_hurt.png',
            happy: '/img/player_panel/warrior_happy.png',
        },
        '마법사': {
            idle:  '/img/face/mage_face_A.png',
            hurt:  '/img/player_panel/mage_hurt.png',
            happy: '/img/player_panel/mage_happy.png',
        },
        '탱커': {
            idle:  '/img/face/tanker_face_A.png',
            hurt:  '/img/player_panel/tanker_hurt.png',
            happy: '/img/player_panel/tanker_happy.png',
        },
        '도적': {
            idle:  '/img/face/rogue_face_A.png',
            hurt:  '/img/player_panel/rogue_hurt.png',
            happy: '/img/player_panel/rogue_happy.png',
        },
    },

    // ── 배틀필드 플레이어 (5상태) ──
    player_battle: {
        '전사': {
            idle:   '/img/player_battle/warrior_idle.png',
            attack: '/img/player_battle/warrior_attack.png',
            skill:  '/img/player_battle/warrior_skill.png',
            hurt:   '/img/player_battle/warrior_hurt.png',
            dead:   '/img/player_battle/warrior_dead.png',
        },
        '마법사': {
            idle:   '/img/player_battle/mage_idle.png',
            attack: '/img/player_battle/mage_attack.png',
            skill:  '/img/player_battle/mage_skill.png',
            hurt:   '/img/player_battle/mage_hurt.png',
            dead:   '/img/player_battle/mage_dead.png',
        },
        '탱커': {
            idle:   '/img/player_battle/tanker_idle.png',
            attack: '/img/player_battle/tanker_attack.png',
            skill:  '/img/player_battle/tanker_skill.png',
            hurt:   '/img/player_battle/tanker_hurt.png',
            dead:   '/img/player_battle/tanker_dead.png',
        },
        '도적': {
            idle:   '/img/player_battle/rogue_idle.png',
            attack: '/img/player_battle/rogue_attack.png',
            skill:  '/img/player_battle/rogue_skill.png',
            hurt:   '/img/player_battle/rogue_hurt.png',
            dead:   '/img/player_battle/rogue_dead.png',
        },
    },

    // ── 배틀필드 몬스터 (5상태) ──
    enemy_battle: {
        '고블린': {
            idle:   '/img/enemy_battle/goblin_idle.png',
            attack: '/img/enemy_battle/goblin_attack.png',
            skill:  '/img/enemy_battle/goblin_skill.png',
            hurt:   '/img/enemy_battle/goblin_hurt.png',
            dead:   '/img/enemy_battle/goblin_dead.png',
        },
        '박쥐': {
            idle:   '/img/enemy_battle/bat_idle.png',
            attack: '/img/enemy_battle/bat_attack.png',
            skill:  '/img/enemy_battle/bat_skill.png',
            hurt:   '/img/enemy_battle/bat_hurt.png',
            dead:   '/img/enemy_battle/bat_dead.png',
        },
        '슬라임': {
            idle:   '/img/enemy_battle/slime_idle.png',
            attack: '/img/enemy_battle/slime_attack.png',
            skill:  '/img/enemy_battle/slime_skill.png',
            hurt:   '/img/enemy_battle/slime_hurt.png',
            dead:   '/img/enemy_battle/slime_dead.png',
        },
        '골렘': {
            idle:   '/img/enemy_battle/golem_idle.png',
            attack: '/img/enemy_battle/golem_attack.png',
            skill:  '/img/enemy_battle/golem_skill.png',
            hurt:   '/img/enemy_battle/golem_hurt.png',
            dead:   '/img/enemy_battle/golem_dead.png',
        },
        '유령': {
            idle:   '/img/enemy_battle/ghost_idle.png',
            attack: '/img/enemy_battle/ghost_attack.png',
            skill:  '/img/enemy_battle/ghost_skill.png',
            hurt:   '/img/enemy_battle/ghost_hurt.png',
            dead:   '/img/enemy_battle/ghost_dead.png',
        },
        '암살자': {
            idle:   '/img/enemy_battle/assassin_idle.png',
            attack: '/img/enemy_battle/assassin_attack.png',
            skill:  '/img/enemy_battle/assassin_skill.png',
            hurt:   '/img/enemy_battle/assassin_hurt.png',
            dead:   '/img/enemy_battle/assassin_dead.png',
        },
        '사제': {
            idle:   '/img/enemy_battle/priest_idle.png',
            attack: '/img/enemy_battle/priest_attack.png',
            skill:  '/img/enemy_battle/priest_skill.png',
            hurt:   '/img/enemy_battle/priest_hurt.png',
            dead:   '/img/enemy_battle/priest_dead.png',
        },
        '중간 보스': {
            idle:   '/img/enemy_battle/midboss_idle.png',
            attack: '/img/enemy_battle/midboss_attack.png',
            skill:  '/img/enemy_battle/midboss_skill.png',
            hurt:   '/img/enemy_battle/midboss_hurt.png',
            dead:   '/img/enemy_battle/midboss_dead.png',
        },
        '최종 보스': {
            idle:   '/img/enemy_battle/finalboss_idle.png',
            attack: '/img/enemy_battle/finalboss_attack.png',
            skill:  '/img/enemy_battle/finalboss_skill.png',
            hurt:   '/img/enemy_battle/finalboss_hurt.png',
            dead:   '/img/enemy_battle/finalboss_dead.png',
        },
    },
};

function getCharImage(section, name, stateName) {
    const sectionMap = CHAR_IMAGES[section];
    if (!sectionMap) return null;
    const charMap = sectionMap[name];
    if (!charMap) return null;
    return charMap[stateName] || charMap['idle'] || null;
}