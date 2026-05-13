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
    // selectedJob:   현재 선택된 직업 (기본 '전사')
    // isEmailAuth:   이메일 인증 거쳐서 가입했는지 (게스트면 false)
    // userEmail:     인증 성공한 이메일 (게스트면 null)
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
        passive: '【패시브】 2턴마다 최대 HP 10% 자동 회복',
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